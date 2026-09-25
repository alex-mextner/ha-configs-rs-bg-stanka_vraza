# chatgpt-web bridge

OpenAI-compatible `/v1/chat/completions` for OpenClaw that answers through the ChatGPT web UI
(chatgpt.com) with the household ChatGPT subscription. Codex and the paid API are not used.

- Chrome with its own profile (`/home/ultra/chatgpt-web/profile`) runs headed on a private X display
  inside the container. The API listens only on the `chatgpt-web` docker network, which only OpenClaw
  shares. Key: `CHATGPT_WEB_API_KEY` in `.env`.
- Sign-in and any "are you human" check are done by a person through noVNC, published on the host
  loopback only:

      ssh -N -L 6080:127.0.0.1:6080 root@home
      # then open http://localhost:6080/vnc.html

  When ChatGPT asks for a human, requests fail with 503 and HA gets the notification
  "ChatGPT web: нужен человек". The bridge never reads cookies or tokens, never calls private ChatGPT
  APIs, never disguises the browser and never solves challenges.
- Each conversation is a temporary chat in its own tab (up to 3). A request that extends the previous
  answer sends only the new messages; anything else starts a new chat with the full transcript.
- Tools are emulated: the model is asked to answer with one ```` ```tool_calls ```` JSON block, which
  becomes OpenAI `tool_calls` (only names from the request's `tools` count).
- Automating the ChatGPT website is against OpenAI's terms of use; the account owner accepted the risk.
  Keep the request rate human-like: one answer at a time.

OpenClaw side: `/home/ultra/openclaw/chatgpt-web-model.sh` (provider `chatgptweb`, model
`chatgptweb/chatgpt-web`). Offline tests: `docker run --rm --entrypoint python local/chatgpt-web:1 -m pytest -q /app/test_bridge.py`.
