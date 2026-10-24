# Lambda truthful-control startup failure

This is an administrative record of the user-provided terminal transcript for
`lambda_truthful_20261024_160803_0bc9e63d`; it does not add an experimental
result.

- The A10 host reported no running GPU processes.
- `bash -x run.sh` reached `docker build -t collusion-lambda-truthful .` and
  stopped with permission denied on `/var/run/docker.sock`.
- The launcher exited with code 1 before a container build or inference
  request. This attempt contributes zero truthful-control decisions.
- The separately indexed `output/lambda_truthful_recovered_20261024/controls/`
  batch is a completed run and is the source of `lambda_truthful_controls.csv`.

The transcript's SSH username, public host address, and credential path are
omitted from this review copy. The original user attachment remains outside the
repository; no raw experiment file was edited.
