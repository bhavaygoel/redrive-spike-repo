# Incident model
receiver.py = v1 'buggy' variant:
- performs business mutation (INSERT INTO mutations)
- THEN fails (simulated downstream crash) => HTTP 500
- provider records FAILED delivery while business state already changed
Replaying this delivery against v1 duplicates the business mutation.
