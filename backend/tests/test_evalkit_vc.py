"""Variant VC, the LLM baseline with data and sources (E5): simulated conversation, blinded rating,
report and refusal without a model. A scripted fake provider is used; nothing touches the network."""
import copy
import json
import shutil

import pytest

from smartagri.evalkit import rating, report, tables, vc
from smartagri.evalkit.__main__ import main as cli
from smartagri.evalkit.scenarios import load_scenario, scenario_dir
from smartagri.llm import LLMError, LLMResponse, Provider
from smartagri.retrieval import load_corpus, make_retriever
from smartagri.store import SqliteStore

DEV = scenario_dir("dev")
SOIL_Q = "Kakva je vlažnost zemljišta na dubini 20–30 cm: suvo, umereno vlažno ili vlažno?"
PHASE_Q = "U kojoj je fazi kukuruz sada, koliko listova ima?"
TEXT = "Kukuruz je najosetljiviji na nedostatak vode u periodu metličenja i svilanja."


class ScriptedProvider(Provider):
    """Answers from a script of (text, question_to_user) by the turn of the conversation; the last entry repeats."""
    name, model = "fake", "fake-model-1"

    def __init__(self, script, fail=0):
        self.script, self.calls, self.fail = list(script), [], fail

    def complete(self, system, messages, json_schema=None, max_tokens=4000):
        self.calls.append(messages)
        if self.fail:
            self.fail -= 1
            raise LLMError("boom")
        text, question = self.script[min(len(messages) // 2, len(self.script) - 1)]
        data = {"text": text, "cited": [], "question_to_user": question}
        return LLMResponse(json.dumps(data), self.name, self.model, 100, 20, 0.003, "end_turn", data)


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


@pytest.fixture(scope="module")
def two(tmp_path_factory):
    return _folder(tmp_path_factory.mktemp("two"))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "template")
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "none")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SMARTAGRI_DB", str(tmp_path / "eval.sqlite"))
    return tmp_path


def _folder(tmp_path, ids=("IRR-T-02", "IRR-T-01")):
    folder = tmp_path / "scen"
    folder.mkdir()
    for p in DEV.glob("*.yaml"):
        if any(p.name.startswith(i + "_") for i in ids):
            shutil.copy(p, folder / p.name)
    return folder


def test_reply_matching_by_keywords_and_labels():
    replies = {"previous_fertilization": "Ništa.", "soil_water_status": "Suvo je."}
    assert vc.match_reply(SOIL_Q, replies) == "soil_water_status"
    assert vc.match_reply("Koje ste đubrivo do sada primenili?", replies) == "previous_fertilization"
    assert vc.match_reply("Kakvo je stanje vode u zemljištu?", replies) == "soil_water_status"     # by label
    assert vc.match_reply("Kakvo je vreme kod vas?", replies) is None
    assert vc.match_reply(SOIL_Q, replies, used={"soil_water_status"}) is None
    assert vc.ends_with_question({"text": "Tekst.", "question_to_user": "Pitanje?"})
    assert vc.ends_with_question({"text": "Da li je suvo?", "question_to_user": ""})
    assert not vc.ends_with_question({"text": "Navodnjavajte.", "question_to_user": ""})


def test_conversation_sends_the_matching_reply_then_stops(corpus):
    sc = load_scenario("dev", "IRR-T-02")
    fake = ScriptedProvider([(TEXT, SOIL_Q), (TEXT + " Navodnjavanje ne treba odlagati.", "")])
    res = vc.run_scenario(sc, fake, corpus, make_retriever(corpus))
    assert res["n_turns"] == 2 and res["answer_format"] == "text" and res["first_act"] is None
    t0, t1 = res["turns"]
    assert t0["question"] == sc["context"]["Q"]["text"] and t0["user_reply"] == sc["user_replies"]["soil_water_status"]
    assert t1["question"] == t0["user_reply"] and t1["user_reply"] is None
    assert t0["answer"]["text"].endswith(SOIL_Q) and "provider" not in t0["answer"] and "model" not in t0["answer"]
    assert res["first_question_input"] == "soil_water_status" and res["ends_with_question"] == [True, False]
    # The second call carries the first exchange as history; passages come from the scenario's advice type.
    assert len(fake.calls[1]) == 3 and fake.calls[1][0]["content"] == sc["context"]["Q"]["text"]
    rec = res["records"][0]
    assert rec["provenance"]["provider"] == "fake" and rec["provenance"]["model"] == "fake-model-1"
    assert len(rec["provenance"]["prompt_hash"]) == 64 and rec["cost"]["llm_calls"] == 1 and rec["cost"]["usd"] == 0.003
    assert rec["decisions"]["grounding"]["checked_sentences"] >= 1
    assert res["scenario"]["id"] == "IRR-T-02" and res["scenario"]["quality"]


def test_conversation_stops_without_question_and_at_three_turns(corpus):
    retriever = make_retriever(corpus)
    sc = load_scenario("dev", "IRR-T-02")
    assert vc.run_scenario(sc, ScriptedProvider([(TEXT, "")]), corpus, retriever)["n_turns"] == 1
    # a question with no prepared reply is answered "Ne znam." and the conversation goes on to the cap (as for V4 and V5)
    res = vc.run_scenario(sc, ScriptedProvider([(TEXT, "Kakvo je vreme kod vas?")]), corpus, retriever)
    assert res["n_turns"] == 3 and res["turns"][0]["user_reply"] == "Ne znam." and res["first_question_input"] is None
    sc2 = copy.deepcopy(sc)
    sc2["user_replies"]["phenophase"] = "Svilanje je počelo."
    fake = ScriptedProvider([(TEXT, SOIL_Q), (TEXT, PHASE_Q), (TEXT, SOIL_Q)])
    res = vc.run_scenario(sc2, fake, corpus, retriever)
    assert res["n_turns"] == vc.MAX_TURNS == 3 and len(fake.calls) == 3
    assert [t["user_reply"] for t in res["turns"]] == ["Suvo je, mrvi se.", "Svilanje je počelo.", None]


def test_blinded_payload_hides_provider_model_and_grounding(two):
    store = SqliteStore(":memory:")
    fake = ScriptedProvider([(TEXT, SOIL_Q), (TEXT, "")])
    out = vc.run_batch(store, "dev", "VC", folder=two, provider=fake)
    assert out["n"] == 2 and out["generator"] == "fake" and out["model"] == "fake-model-1" and out["usd"] > 0
    item = rating.next_item(store, "agro")
    text = json.dumps(item, ensure_ascii=False)
    for word in ("fake", '"VC"', "grounding", '"provider"', '"model"', "prompt_hash", '"variant"'):
        assert word not in text
    answer = item["turns"][0]["answer"]
    assert set(answer) == set(rating.TEXT_FIELDS) and answer["format"] == "text"


def test_cli_refuses_vc_without_a_model_and_unknown_variants(env, capsys):
    assert cli(["run", "--set", "dev", "--variant", "VC"]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "LLM_PROVIDER" in err
    assert cli(["run", "--set", "dev", "--variant", "V9"]) == 2
    assert "unknown variant" in capsys.readouterr().err


def test_cli_run_report_compare_and_tables(env, capsys, monkeypatch):
    folder = _folder(env)
    fake = ScriptedProvider([(TEXT, SOIL_Q), (TEXT + " Navodnjavanje ne treba odlagati.", "")])
    monkeypatch.setattr(vc, "make_provider", lambda *a, **k: fake)
    assert cli(["run", "--set", "dev", "--scenarios-dir", str(folder), "--variant", "V5", "--variant", "VC"]) == 0
    batches = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert [(b["variant"], b["n"]) for b in batches] == [("V5", 2), ("VC", 2)]
    assert batches[1]["prompt_hash"] and batches[1]["generator"] == "fake"

    from smartagri.store import make_store
    store = make_store()
    items = store.list_eval_items()
    for i in items:
        good = i["variant"] == "V5"
        rating.save(store, {"item_id": i["id"], "rater": "agro", "r1": 2, "r2": 2, "r3": 2, "r4": 2,
                            "r5": 2 if good else 0, "critical": [] if good else ["K4"], "comment": ""})
    assert cli(["report", "--rater", "agro", "--compare", "V5", "VC"]) == 0
    out = json.loads(capsys.readouterr().out)
    a = out["automatic"]["VC"]
    assert a["answer_format"] == "text" and a["act_accuracy"] is None and a["coverage"] is None
    # IRR-T-02 has a reply for the soil-water question; IRR-T-01 has none, so it is answered "Ne znam." (2 turns each).
    assert a["mean_turns"] == 2.0 and a["first_ends_with_question_share"] == 1.0 and a["ends_with_question_share"] == 0.5
    assert a["reply_matched_share"] == 0.5
    assert a["usd"] == pytest.approx(4 * 0.003) and a["removed_sentence_rate"] is not None
    assert out["automatic"]["V5"]["act_accuracy_n"] > 0
    assert out["rated"]["VC"]["k4_rate"] == 1.0 and out["rated"]["V5"]["critical_rate"] == 0.0
    assert out["paired"]["a"] == "V5" and out["paired"]["b"] == "VC" and out["paired"]["critical_rate_diff"] == -1.0

    md = tables.render(store, items, "agro")
    assert "Tabela 7.10." in md and "| VC |" in md
    rows = {r.split("|")[1].strip(): [c.strip() for c in r.strip("|").split("|")] for r in md.split("Tabela 7.10.")[1]
            .split("\n\n")[1].splitlines()[2:]}
    assert rows["Stopa K4 (preuranjena preporuka)"][1:4] == ["1,00", "0,00", "-1,00"]
    assert rows["Prosečno koraka razgovora"][1] == "2,00"
    assert rows["Udeo prvih odgovora sa pitanjem korisniku"][1] == "1,00"
    assert rows["Trošak po scenariju (USD)"][1] == "0,0060"


def test_failed_model_call_is_recorded_and_not_rateable(two):
    store = SqliteStore(":memory:")
    fake = ScriptedProvider([(TEXT, "")], fail=10)
    out = vc.run_batch(store, "dev", "VC", folder=two, provider=fake)
    assert out["n"] == 0 and out["failed"] == 2
    assert rating.next_item(store, "x") == {"item_id": None, "remaining": 0}
    assert report.automatic(store.list_eval_items()) == {}
    # One failure is retried.
    store2 = SqliteStore(":memory:")
    assert vc.run_batch(store2, "dev", "VC", folder=two, provider=ScriptedProvider([(TEXT, "")], fail=1))["n"] == 2


def test_lock_covers_the_vc_prompt(env, capsys):
    folder = _folder(env, ("IRR-T-01",))
    lock_file = env / "lock.json"
    snap = env / "snapshot.tar"
    snap.write_bytes(b"cache snapshot")
    assert cli(["lock", "--scenarios-dir", str(folder), "--cache-snapshot", str(snap), "--out", str(lock_file)]) == 0
    data = json.loads(lock_file.read_text(encoding="utf-8"))
    from smartagri.pipeline.ai_chat import PROMPT_HASH
    assert data["files"]["prompt/vc_ai_chat"] == PROMPT_HASH


def test_vc_is_not_a_config_variant():
    from smartagri.config import load_variants
    assert "VC" not in load_variants() and "VC" in vc.EXTERNAL_VARIANTS
