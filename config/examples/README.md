# Config Examples

These files are safe examples for local setup and deployment bootstrap.

Runtime files still live at the repo root by default:

- `tasks.json`
- `channels.json`
- `config.content.json`
- `config.secrets.json`

The root runtime files are environment-specific and ignored by Git. Do not commit production credentials, channel IDs, task state, backup snapshots, or local `.env` files.

Suggested bootstrap:

```bash
cp config/examples/config.content.example.json config.content.json
cp config/examples/config.secrets.example.json config.secrets.json
cp config/examples/channels.example.json channels.json
cp config/examples/tasks.example.json tasks.json
```

After bootstrap, edit the root runtime files or use the Streamlit console.
