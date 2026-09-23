# Verificare milestone 1 — 12 septembrie 2026

- Python 3.12, dependențe instalate și importate efectiv.
- 12 teste pytest trecute; verificare Ruff trecută.
- CLI demo: 12 candidați sintetici, oprire după `extract`, reluare într-un proces separat,
  12 adjudecări și 10 rezultate în raport. Raportul poate fi regenerat prin `--resume`.
- Test de eșec al reviewer B: checkpoint păstrat; reluarea nu repetă reviewer A.
- Teste pentru deduplicare/proveniență, DOI-uri conflictuale și matching ambiguu,
  citate inexistente, output invalid, acord/dezacord, verdict uncertain, lipsă abstract,
  rezultate goale, erori HTTP și cache-ul adaptorului de model.
- Smoke test live Europe PMC: 3 înregistrări publice recuperate, toate cu abstract.
  Snapshot: `examples/live-connector/retrieved.json`; payload sursă: baza SQLite alăturată.
  Acest snapshot nu reprezintă lucrări evaluate sau un top științific.
- Nu a fost executat un run cu modele LLM externe. Testul adaptorului live folosește
  un model substituit; cheile și model IDs trebuie configurate înaintea verificării live.

`requirements.lock.txt` păstrează versiunile instalate în mediul testat. Pentru reproducere:

```sh
pip install -r requirements.lock.txt
pip install --no-deps -e .
pytest -q
```

Manifestul demo și bazele SQLite incluse sunt date de exemplu. Pentru experimente noi,
folosește un director nou de run, așa cum este descris în README.

## Interfață — verificare 14 septembrie 2026

18 teste trecute, inclusiv randarea interfeței Streamlit, filtrarea clasamentului,
validarea formularului, lansarea workerului, blocarea lansărilor duplicate și progresul
persistent. Cheile sunt excluse din argumentele procesului și din fișierele de configurare;
mesajele de eroare ale furnizorilor sunt filtrate înainte de afișare.

Verificat în browser: pagina de rezultate, formularul unei cercetări noi, lansarea unui
demo de 12 candidați, pauza după extragerea dovezilor și reluarea din interfață.
Tema luminoasă este stabilită de launcher pentru un contrast lizibil.
