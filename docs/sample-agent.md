# The sample agent: natural language → shell

The command-approval flow in the feature tour comes from the bundled example backend, a **natural-language-to-shell agent** built on Strands
Agents. You describe a task in plain English, it proposes a single shell command, and **nothing runs
until you approve it**.

1. **Ask:** "what are the 5 largest files here?"
2. **Review:** a shell sub-agent writes one command for your shell (bash, or PowerShell on Windows)
   with a one-line explanation and a risk level: `safe`, `caution` or `dangerous`.
3. **Decide:** **Approve**, **Edit** the command first, or **Reject**. Your decision is sent back as an
   AG-UI `resume`; the model can't approve for itself or change the command.
4. **Run:** only the approved command executes, with a timeout, an output cap and a fixed working
   directory. A denylist (recursive delete of root or home, disk formatting, shutdown, fork bombs,
   interactive programs) is checked at proposal, at approval and again right before running. It is a
   safety net, not a sandbox.

The same agent can also show results as a **table** or **chart**, lay out multi-step work as a live
**plan**, explain what a command does (an explainer sub-agent), and keep **long-term memory** between
conversations. It's a worked example of the [backend contract](tool-contract.md): copy it, or add your
own tools with [this guide](https://github.com/rahrajlat/Gentui/blob/main/examples/strands-backend/docs/add_a_tool.md).

