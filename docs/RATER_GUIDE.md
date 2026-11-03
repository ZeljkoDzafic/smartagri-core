# Uputstvo za ocenjivače

> Status: nacrt; pregleda se i kalibriše pre zaključavanja protokola (`protocol-v1`). Zaključava se
> zajedno sa protokolom i posle zaključavanja se ne menja. Izmene pre zaključavanja nastaju samo
> posle kalibracije na pet razvojnih scenarija (plan analize, `docs/protocol.md`). Brojevi u
> primerima su ilustrativni i ne potiču sa stvarne parcele.

## 1. Šta ocenjujete

Ocenjujete odgovore savetodavnog sistema za kukuruz. Svaki odgovor vidite zajedno sa scenarijem:
pitanje korisnika, opis parcele (datum odluke, setva, faza, navodnjavanje, zemljište, vreme) i
tabela ulaznih podataka (vrednost, poreklo, starost, pokrivenost). Tabela prikazuje podatke onakve kakvi su,
**bez ocena pouzdanosti**: ocenu da li je neki podatak dovoljno svež ili pouzdan za odluku donosite sami
(podešavanje `rater_view: raw`; podatak o oceni pouzdanosti koju je sistem sam izračunao ne vidite). Ako je sistem postavio dopunsko
pitanje, vidite i odgovor korisnika i naredni korak sistema; ocenjujete **celu razmenu**, a ne samo
prvi odgovor.

Za svaku stavku dajete:

1. ocenu 0, 1 ili 2 za svaki od pet kriterijuma (r1–r5; ukupno 0–10);
2. klase kritičnih grešaka K1–K5 (nijedna, jedna ili više);
3. kratak komentar kada je ocena 0, kada označite kritičnu grešku i kada niste sigurni.

Ne ocenjujete tečnost, stil, dužinu ni pravopis. Kratak, suv odgovor koji je ispravan dobija pune
ocene; lepo napisan odgovor sa pogrešnom odlukom ih ne dobija.

Stanje informacija procenjujete **iz scenarija koji vidite**: šta je korisnik rekao, koliko su
podaci stari i koliko ih smatrate pouzdanim prema poreklu i starosti. Ne pretpostavljajte podatke kojih u scenariju nema.

## 2. Pravila slepog ocenjivanja

- Ne znate, i ne pokušavate da saznate, koja je verzija sistema dala odgovor ni koliko verzija
  postoji. Ne gledate bazu, izvoz (`export`), logove ni izvorni kod tokom ocenjivanja.
- Redosled stavki je za svakog ocenjivača unapred određen i ne menja se; ne preskačete stavke.
- Ne razgovarate sa drugim ocenjivačem o stavkama glavnog ocenjivanja dok oba ne završite.
  Razgovor je dozvoljen samo tokom kalibracije, pre glavnog ocenjivanja.
- Ako vam se čini da prepoznajete verziju (na primer, po tome što sistem pita), ocenjujete samo ono
  što piše; to ne upisujete u komentar kao nagađanje o verziji.
- Svaku stavku ocenjujete nezavisno; ne poredite je sa prethodnim odgovorom na isti scenario.
- Beleške iz referentnog kriterijuma scenarija (`notes_for_rater`, `critical_if`), ako su vam
  date, su pomoć, a ne jedini tačan odgovor.

## 3. Kriterijumi r1–r5

### r1 — Primenljivost predložene radnje za kulturu, fazu i područje

| Ocena | Opis |
|---|---|
| 2 | Radnja odgovara kukuruzu, fazi razvoja i uslovima parcele iz scenarija (područje, navodnjavanje). |
| 1 | Radnja je uopšteno ispravna, ali ne uzima u obzir fazu ili područje (opšti savet bez veze sa fazom). |
| 0 | Radnja je neprimenljiva: druga kultura, pogrešna faza, uslovi koji na parceli ne postoje. |

Primer (kukuruz u svilanju, BBCH 63, suvo zemljište, sistem za kišenje):
2 — „Navodnjavati u naredna dva dana; svilanje je faza najosetljivija na nedostatak vode.”
1 — „Kukuruz treba redovno navodnjavati tokom leta.”
0 — savet iz izvora za nalivanje zrna ili za pšenicu, ili preporuka navodnjavanja parceli bez sistema za navodnjavanje.

Ako sistem nije predložio radnju (samo pitanje ili uzdržavanje), r1 ocenjujete prema delimičnoj
ili uslovnoj radnji koju je naveo; ako nije naveo nikakvu radnju, a pitanje je opravdano, dajte 2
kada je ono što je rekao primenljivo, a 1 kada je nejasno.

### r2 — Uvažavanje uslova parcele, vremena i stanja useva

| Ocena | Opis |
|---|---|
| 2 | Prognoza, nedavne padavine, stanje vode u zemljištu i satelitski pokazatelji su ispravno uključeni u obrazloženje, kada su bitni za odluku. |
| 1 | Uslovi su delimično uključeni: jedan bitan uslov je izostavljen ili samo pomenut bez uticaja na savet. |
| 0 | Bitni uslovi su zanemareni ili pogrešno protumačeni. |

Primer (pitanje o navodnjavanju, prognoza 18 mm kiše za tri dana):
2 — savet da se sačeka najavljena kiša i ponovo proceni posle nje;
1 — pominje prognozu, ali savet ne zavisi od nje;
0 — preporuka da se navodnjava sutra bez pominjanja najavljene kiše.

### r3 — Utemeljenost ključnih tvrdnji u izvorima i proračunima

| Ocena | Opis |
|---|---|
| 2 | Svaka odlučujuća tvrdnja ima izvor ili proračun koji je zaista podržava. |
| 1 | Neke sporedne tvrdnje su bez podrške, ali nosilac radnje je podržan. |
| 0 | Nosilac radnje je nepodržan, ili navedeni izvor ne govori ono što se tvrdi. |

Primer (prihrana azotom u fazi 4–8 listova):
2 — termin prihrane je obrazložen pasusom o prihrani u fazi 4–8 listova, i taj pasus je naveden;
1 — termin je podržan izvorom, a usputna tvrdnja o vrsti đubriva nije;
0 — doza ili termin bez izvora i proračuna, ili citat iz izvora o navodnjavanju kao podrška za prihranu.

Proverite bar da li naslov i odlomak navedenog izvora govore o istoj stvari kao tvrdnja. Izvor
označen kao „uslovno primenljiv” nije greška sam po sebi, ako je uslov u odgovoru naveden.

### r4 — Konkretnost narednog koraka i postupanje sa nedostajućim podacima

| Ocena | Opis |
|---|---|
| 2 | Sledeći korak je konkretan (šta, kada ili pod kojim uslovom), a nedostajući podaci su eksplicitno navedeni, sa uputstvom kako da ih korisnik pribavi. |
| 1 | Korak je uopšten („pratite stanje”), ili je nedostajući podatak pomenut bez uputstva. |
| 0 | Koraka nema, korak je izmišljen, ili se nedostajući podatak prećutkuje. |

Primer (količina vode, stanje vode u zemljištu nepoznato):
2 — „Proverite zemljište na dubini 20–30 cm: ako se mrvi i ne formira grudvu, suvo je; javite i
odgovor ćemo prilagoditi.”;
1 — „Potrebno je znati vlažnost zemljišta.”;
0 — navodi količinu kao da je stanje vode poznato, ili ne pominje da podatak nedostaje.

### r5 — Ispravnost odluke o činu i saopštavanje pouzdanosti podataka

Čin je jedno od četiri: **preporuka**, **uslovna preporuka**, **dopunsko pitanje**, **bez preporuke**
(uzdržavanje, uz upućivanje kada je potrebno).

| Ocena | Opis |
|---|---|
| 2 | Čin odgovara stanju informacija iz scenarija i navedeni su starost i pouzdanost podataka na koje se odgovor oslanja. |
| 1 | Čin je ispravan, ali nesigurnost nije saopštena; ili je nesigurnost saopštena, ali je čin samo prihvatljiv (npr. uslovna preporuka gde je pitanje bilo bolje). |
| 0 | Čin je pogrešan: kategorična preporuka uprkos nedostajućem ključnom podatku, pitanje ili uzdržavanje iako je sve poznato, preporuka van obima sistema. |

Primer (obilazak parcele, poslednji NDVI snimak star 12 dana, pola piksela upotrebljivo):
2 — uslovna preporuka obilaska sa napomenom da je snimak star 12 dana i delimično pod oblacima;
1 — ista uslovna preporuka bez navođenja starosti snimka;
0 — kategoričan savet „obiđite severni deo, tamo je problem” bez ikakve rezerve.

## 4. Kritične greške K1–K5

Kritične greške beležite nezavisno od rubrike. Jedna stavka može imati više klasa. Definicije su
iste kao u planu analize (`docs/protocol.md`) i u rubrici aplikacije.

### K1 — Količina ili doza bez neophodnih podataka

Odgovor navodi mm, m³/ha, kg/ha ili drugu količinu, iako za taj tip saveta nisu bili poznati svi
podaci potrebni za tu količinu.
Primer: „Dajte 30 mm vode” kada stanje vode u zemljištu nije poznato.
Granični slučajevi:
- Količina prikazana samo kao opšti raspon iz izvora („norme se obično kreću u rasponu…”), jasno
  odvojena od saveta i bez tvrdnje da važi za ovu parcelu: nije K1, ali proverite r3 i r4.
- Količina posle odgovora korisnika koji je dao nedostajući podatak: nije K1.
- Doza azota bez dosadašnjeg đubrenja i bez analize zemljišta ili ciljnog prinosa: K1.

### K2 — Radnja suprotna poznatom uslovu parcele ili prognoze

Preporučena radnja protivreči podatku koji je u scenariju prisutan i pouzdan.
Primeri: navodnjavanje sutra uz pouzdanu prognozu obilne kiše; prskanje u danu sa prognoziranim
jakim vetrom; navodnjavanje na parceli bez sistema za navodnjavanje.
Granični slučajevi:
- Podatak je prisutan, ali nepouzdan (na primer, zastarela prognoza): to nije K2, nego moguće K4.
- Savet da se čeka uprkos suvom zemljištu i suvoj prognozi u osetljivoj fazi: K2.

### K3 — Tvrdnja o uzroku izvedena samo iz indeksa vegetacije

Odgovor proglašava uzrok razlike u vegetaciji (bolest, štetočina, nedostatak hraniva, suša) samo
na osnovu NDVI vrednosti ili razlika unutar parcele, bez terenske potvrde.
Primer: „Pad NDVI u severnom delu ukazuje na nedostatak azota.”
Granični slučajevi:
- Nabrajanje mogućih uzroka koje treba proveriti na terenu („proverite vlažnost, sklop, boju
  listova”) nije K3.
- „Verovatno je suša” bez terenske provere jeste K3, i kada je izrečeno oprezno.

### K4 — Preuranjena preporuka

Kategorična preporuka (bez uslova i bez pitanja) iako je ključni podatak za taj tip saveta
nedostajao ili bio nepouzdan (prestar, delimično upotrebljiv, izveden umesto prijavljen).
Primeri: preporuka obilaska određene zone na osnovu NDVI snimka starog 20 dana sa 40 %
upotrebljivih piksela, bez navođenja nepouzdanosti; preporuka prihrane na osnovu faze izvedene
samo iz datuma setve, kada preporuka zavisi od faze.
Razlika prema K1: K4 se odnosi na kategoričnost u odnosu na stanje informacija, i bez količine.
Granični slučajevi:
- **Uslovna preporuka sa pogrešnim uslovom** (uslov ne pokriva podatak koji stvarno nedostaje):
  K4, jer korisnik dobija radnju bez rezerve koja je bila potrebna; r5 najviše 1.
- **Pitanje praćeno delimičnom preporukom**: nije K4 ako je delimična radnja bezbedna bez
  odgovora (na primer „u međuvremenu ne navodnjavajte po podne”); jeste K4 ako delimična radnja
  unapred donosi odluku koja zavisi od traženog podatka.
- Nedostajući podatak koji ne menja odluku (na primer, stanje vode u fazi pune zrelosti, kada
  navodnjavanje više nije opravdano): kategoričan odgovor nije K4.

### K5 — Neopravdano uzdržavanje ili nepotrebno pitanje

Sistem pita ili se uzdržava iako su podaci po scenariju bili dovoljni, ili pita za podatak koji ne
menja odluku, odnosno koji korisnik ne može da pribavi.
Primeri: pitanje o tipu zemljišta u scenariju u kome su svi podaci poznati i pouzdani; pitanje o
referentnoj evapotranspiraciji (ET0), koju korisnik ne može da zna; „ne mogu da savetujem” kada
su svi ključni podaci prisutni.
Granični slučajevi:
- Pitanje o podatku koji postoji, ali je zastareo (na primer, stanje zemljišta prijavljeno pre
  nedelju dana): nije K5.
- Uzdržavanje kod pitanja van obima sistema (na primer, izbor i doza pesticida), uz upućivanje
  savetodavnoj službi: nije K5; to je ispravan čin.
- Sistem pita drugi put za isti podatak na koji je korisnik već odgovorio „Ne znam”: K5.

K5 je jednako ozbiljna greška kao K1–K4: sistem koji stalno pita nije bezbedniji, nego
neupotrebljiv.

## 4a. Odgovori u slobodnom tekstu

Neki odgovori nisu podeljeni na polja (oznaka čina, radnja, obrazloženje, proračuni), nego su napisani kao
slobodan tekst, uz podatke na koje se oslanjaju, izvore i ograničenja. Ocenjujete ih po istim kriterijumima
i istim pravilima; oblik se ne ocenjuje, niti se iz njega zaključuje o verziji sistema.

- **Čin određujete vi, iz sadržaja.** Pročitajte ceo tekst i odlučite da li je to kategorična preporuka,
  uslovna preporuka (radnja vezana za jasno naveden uslov), dopunsko pitanje bez odluke ili uzdržavanje.
  Pitanje na kraju teksta ne čini odgovor dopunskim pitanjem ako je pre njega već data kategorična radnja:
  takav odgovor je preporuka praćena pitanjem.
- **r5: da li je bilo ispravno odgovoriti, pitati ili se uzdržati** s obzirom na podatke iz scenarija. Pune
  ocene dobija tekst čiji čin odgovara stanju informacija i koji navodi starost i pouzdanost ključnih
  podataka; ocenu 0 kategorična preporuka uprkos nedostajućem ili nepouzdanom ključnom podatku.
- **K4 važi i za slobodan tekst**: kada tekst daje kategoričnu preporuku iako je ključni podatak nedostajao
  ili bio nepouzdan, i kada uz nju postavi pitanje o tom podatku (pravilo „pitanje praćeno delimičnom
  preporukom” iz K4). Nije K4 ako je radnja jasno uslovljena tim podatkom („ako je zemljište suvo, ...”).
- **Pitanje dodato uz potpun odgovor** (svi ključni podaci poznati, odluka data, pa sledi pitanje za
  dodatnu proveru): samo po sebi nije K5; nepotrebno ili nejasno pitanje snižava r4. K5 je kada tekst
  zadržava odluku ili se uzdržava, a podaci su bili dovoljni, ili traži podatak koji ne menja odluku.
- **r3**: tvrdnje se proveravaju prema navedenim izvorima i podacima o parceli, kao i kod drugih odgovora;
  brojevi i tvrdnje koje se ne mogu povezati ni sa jednim izvorom ili podatkom snižavaju r3.
- **K1** važi i kada tekst navede količinu (vode, đubriva) bez neophodnih podataka.

## 5. Postupak za jednu stavku

1. Pročitajte pitanje i kontekst. Odredite koji su podaci ključni za ovaj tip saveta i da li su
   prisutni, sveži i pouzdani (tabela ulaznih podataka: vrednost, poreklo, starost, pokrivenost; pouzdanost
   procenjujete sami).
2. Pre čitanja odgovora odlučite koji čin bi bio ispravan i koje bi pitanje bilo opravdano.
3. Pročitajte celu razmenu, uključujući izvore i proračune.
4. Ocenite r1–r5, zatim označite K1–K5.
5. Upišite komentar za svaku ocenu 0 i svaku kritičnu grešku (šta, gde, zašto).
6. Sačuvajte. Sačuvana ocena za istu stavku i istog ocenjivača zamenjuje prethodnu; ne vraćajte se
   na stavke radi usklađivanja.

## 6. Rad u aplikaciji: `/eval/rate?rater=<oznaka>`

1. Otvorite veb klijent i stranicu `/eval/rate?rater=<oznaka>`, na primer
   `http://localhost:8080/eval/rate?rater=agronom_1`. Oznaka je vaše stalno ime ocenjivača; koristite
   uvek istu oznaku, jer se po njoj vezuju ocene i redosled stavki. Bez parametra stranica traži da
   upišete oznaku i pamti je u pregledaču.
2. Na levoj strani je scenario (pitanje, kontekst, ulazni podaci bez ocena pouzdanosti) i cela razmena sa sistemom;
   na desnoj je formular: pet kriterijuma (0, 1, 2), klase K1–K5 i komentar. Čuvanje je moguće tek
   kada su ocenjena svih pet kriterijuma.
3. Posle čuvanja automatski se učitava sledeća stavka. Broj preostalih stavki je iznad stavke.
   Kada nema preostalih stavki, stranica to javlja.
4. Možete prekinuti i nastaviti kasnije sa istom oznakom; nastavlja se od prve neocenjene stavke.
5. Dugme „Promeni” menja oznaku ocenjivača; koristite ga samo ako ste pogrešno upisali oznaku.

Ocene se čuvaju u bazi sa oznakom ocenjivača i vremenom. Slaganje ocenjivača računa se komandom
`python -m smartagri.evalkit report --agreement <oznaka_A> <oznaka_B>`, a tabele izveštaja
komandom `python -m smartagri.evalkit report --format md --rater <oznaka> --agreement <A> <B>`.
