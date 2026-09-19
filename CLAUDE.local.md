# Claude

## Instructions
- When running python scripts or install python packages, use the conda environment `dagi`.
    - e.g. `conda run -n dagi python example.py`
- `conda run` fully buffers stdout when not attached to a TTY (pipes, redirects, background jobs all look like hangs). For long-running commands or when streaming output matters, call the interpreter directly: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest ...`
- Always update `README.md` and `TODO.md` after completing a task. Ensure that these 2 documents remain up-to-date with the actual status of this repo.