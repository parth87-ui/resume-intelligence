# models/

Persisted ML artefacts live here. The shipped pipeline fits its TF-IDF
vectoriser per request (a two-document corpus, so fitting is trivially cheap)
and needs nothing on disk, which is why the directory is otherwise empty.

Use it when you extend the system with anything that must be trained once and
reused, for example:

- a vectoriser or embedding index fitted over a corpus of real job descriptions
- a trained classifier for resume section detection
- a cached sentence-embedding model for semantic similarity

Load such artefacts through a module in `backend/ml/` so the rest of the code
keeps talking to `SimilarityModel` / `NLPPipeline` rather than to files.

Nothing here is committed: see `.gitignore`.
