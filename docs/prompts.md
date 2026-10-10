# Run a set of prompts: `--prompts`

Put the messages in a YAML file and Gentui sends them for you, one after the other, each when the previous answer is
complete:

```yaml
# prompts.yml
prompts:
  - What are the 5 largest files here?
  - text: Now plot them as a bar chart
```

```bash
gentui http://localhost:8000/agent --prompts prompts.yml --record baseline
```

A bare list works too, and each item is a string or a mapping with a `text` key. Combined with `--record` this gives you a
repeatable run you can keep. If the agent asks for approval, the queue waits for your answer. When the last prompt has been
answered the app stays open (type `/quit` to leave), so you can carry on the conversation by hand.
