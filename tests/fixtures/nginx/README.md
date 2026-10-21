# nginx fixtures (SAAS-029)

- `nginx_T_*.txt` — shaped like `docker exec manasety-nginx-1 nginx -T`
  output, with only `server_name` / file-header lines kept. **Synthetic**:
  replace with the real (secret-stripped) dump from the server when
  Abdelhamid attaches it; the parser only reads `# configuration file`
  headers and `server_name` lines.
- `demo_block.golden.conf` — what `school.conf.j2` renders for `demo`.
  `flask nginx-sync --check` on production must show no difference
  against the hand-written demo block except the generated header.
