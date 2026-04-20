# forge-plugin-example

Reference implementation of a forge plugin. Demonstrates:

- Declaring a `forge.plugins` entry point
- Registering an `Option` (`example.hello_banner`)
- Registering a `Fragment` that the option enables
- Shipping fragment files (`files/` + `inject.yaml`) inside the plugin package

Install:

```bash
pip install -e .
```

Verify:

```bash
forge plugins list
```

Use:

```bash
forge --yes --no-docker --backend-language python \
      --set example.hello_banner=true \
      --project-name banner-demo --output-dir /tmp
```

See `docs/plugin-development.md` for the full guide.
