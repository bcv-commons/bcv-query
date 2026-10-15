# licenses — the data sources the services serve, with their licences

`sources.json` is the one list of data sources behind the public APIs: for each source its name, licence (SPDX id where there
is one), licence URL, required attribution, home URL, and a note where the licence is mixed or unclear. It also states the
licence of the service code (`code_license`).

Each service maps its routes to these source ids in its own file: `shoresh/licenses.json` and `bcv-RAG/server/licenses.json`.
Both serve the result at `GET /licenses` (shoresh) and `GET /api/licenses` (bcv-rag), and every response carries
`Link: <…licenses?path=<route>>; rel="license"`. Tests in each service fail when a route has no entry or names a source not
listed here.

"unknown" means no licence statement has been found yet; fix the entry here when one is.
