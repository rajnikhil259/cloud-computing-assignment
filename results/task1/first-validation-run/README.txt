First teacher validation run (no newline stop sequence): 90.0% JSON validity, 57.0% full frame.
9 of the 10 invalid replies were a correct JSON line followed by "\n\n(Note: ...)", which led to adding
"\n" to the stop sequences in worker/worker.py. Kept for the record; the run with the final settings is in results/.
