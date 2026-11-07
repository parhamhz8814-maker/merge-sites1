# Run doc — CP.Shop static site (Desktop/gametop)

## Reproduce artifacts
None required. This is a plain static HTML site with no build step, no dependencies,
and no env files. Optional (MCP server only, not needed for the site preview):
`gametop/mcp-server/.venv` — recreate with
`python -m venv gametop/mcp-server/.venv && gametop/mcp-server/.venv/Scripts/python -m pip install "mcp[cli]"`.

## Run the server
No server needed — register the static entry file directly:
`register_preview { htmlPath: "C:\Users\Mr laptop\Desktop\gametop\index.html" }`.
Pages: `index.html` (store), `logos.html` (logo picker).
