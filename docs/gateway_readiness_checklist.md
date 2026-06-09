# InsightBot Gateway Readiness Checklist

InsightBot is currently a Streamlit workbench running behind `insightbot-web.service`.
The existing `8501` access path is a production reality, not the final product
gateway target.

Use this checklist before treating the workbench as gateway-ready on Tencent Cloud.

## Target Shape

- Public route: `/insightbot/`
- Public access: shared gateway on `80/443`
- Streamlit upstream: `127.0.0.1:8501`
- Scheduler: systemd service with no public port
- Root `/`: reserved for the shared app index

## Required Checks

- `/insightbot/` renders non-empty content on first load.
- Refreshing `/insightbot/` does not show a blank page.
- Streamlit static assets load under the gateway path.
- Streamlit WebSocket traffic works through the gateway path.
- Browser requests do not call `http(s)://<host>:8501`.
- Health or readiness checks are available through the gateway when exposed.
- Downloads, redirects, and links do not escape to the internal app port.
- Production service binds to `127.0.0.1`, not `0.0.0.0`.

## Current Known Gap

The app has not yet been validated under a path prefix. Before cutover, test the
actual gateway config against the running Streamlit app and record the result in
the deployment guide.
