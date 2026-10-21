"""Legacy seed scripts — NOT USED (SAAS-041).

They were written before school_id became NOT NULL, they create known
default passwords, and they are not maintained. Importing the package
stops here so `python -m seeds.<anything>` can't run by mistake.

  • A real school:     the console wizard, or `flask school-provision`
  • Test schools:      `flask seed-test-schools` (test-a / test-b)

The files stay only as a reference of which entities exist.
"""
raise SystemExit(
    "seeds/ is legacy and must not be run (written before school_id NOT NULL; default passwords). "
    "Use `flask school-provision` for a real school or `flask seed-test-schools` for test data."
)
