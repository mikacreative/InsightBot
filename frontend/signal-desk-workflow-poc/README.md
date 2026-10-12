# Signal Desk workflow prototype UI

This isolated frontend uses React and React Flow to render the canonical plan
returned by the local Kestra prototype server. It has no client materials,
credentials, remote assets, or real publishing integrations.

```bash
npm --cache /private/tmp/signaldesk-poc-npm-cache ci
npm --cache /private/tmp/signaldesk-poc-npm-cache run build
```

The Python prototype server serves `dist/` at `http://127.0.0.1:18977/` and owns
all `/api/` endpoints. The UI sends the returned CSRF token with each mutation.
Node positions, connections, configuration, conversation changes, and execution
all use the same server plan. Rejected graph changes are restored on screen.
Planning, schedule installation, execution, approval, and publication states are
reported from the server; the frontend does not simulate successful execution.

React Flow supports dragging and connecting real plan nodes. The server validates
every graph change and retains a frozen plan for each execution. The prototype
only accepts its approved modules; it is not an unrestricted workflow builder.

Direct runtime dependencies are React, React DOM, and React Flow, all under the
MIT license. Their notices and production dependency licenses ship as
`public/third-party-licenses.txt` in the static build.
