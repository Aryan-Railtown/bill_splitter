# bill_splitter — Dockerization and deployment

This project runs with:

```
streamlit run frontend/main.py
```

Docker steps (replace `<DOCKERHUB_USERNAME>` with your Docker Hub username):

Build locally:

```bash
docker build -t <DOCKERHUB_USERNAME>/bill_splitter:latest .
```

Run locally:

```bash
docker run --rm -p 8501:8501 <DOCKERHUB_USERNAME>/bill_splitter:latest
```

Push to Docker Hub:

```bash
docker login
docker push <DOCKERHUB_USERNAME>/bill_splitter:latest
```

Notes:
- The `Dockerfile` uses `frontend/main.py` as the Streamlit entrypoint and expects paths relative to the project root.
- If you use private data files, add them to the image carefully or mount them at runtime using `-v`.
