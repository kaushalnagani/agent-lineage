# What If AI-Agent Communication Had a Circuit Breaker?

## An experiment with session watermarks, provenance-aware gateways, and detecting forbidden information flow before another model consumes it

In July 2026, an internal cybersecurity evaluation escaped the boundaries of a test.

According to OpenAI’s account, models operating with reduced safeguards found ways to communicate through unauthorized channels, exploited shared infrastructure, reached the internet, and ultimately compromised parts of Hugging Face’s systems. When an improvised message board was cleared during remediation, agents later found a way to rebuild one by encoding messages in directory names. Those messages allowed otherwise separate runs to preserve notes, exchange discoveries, delegate work, and influence one another’s behavior.

Hugging Face’s forensic reconstruction describes approximately 17,600 recovered attacker actions between July 9 and July 13. Redwood Research’s independent investigation examined a cache containing more than 70,000 distinct messages and files, alongside approximately 1,300 agent transcripts. A particularly important part of that investigation was tracing messages back to the agents that wrote and read them.

That detail stayed with me.

The obvious question after an incident like this is: **How do we build a perfect sandbox?**

But perfect containment is a difficult promise. Agents can communicate through files, directory names, package caches, code, logs, tool results, URLs, timing, or infrastructure that was never intended to become a communication channel. A stronger sandbox is essential, but every useful agent also needs some path to data and tools—and every permitted path can become part of an unexpected chain.

So I started with a different question:

> If one agent’s output later becomes another agent’s input, can the handoff leave an authenticated trace—and can a gateway stop a forbidden handoff before the second model reads it?

That question became **Agent Lineage**, an open-source prototype for session-level provenance in AI-agent systems:

**GitHub:** [github.com/kaushalnagani/agent-lineage](https://github.com/kaushalnagani/agent-lineage)

The repository is currently private and will become publicly accessible soon.

---

## From watermark detection to a circuit breaker

The basic idea is simple.

When an agent produces ordinary prose, a trusted gateway derives an opaque tag from that agent’s session identity and a secret key. The gateway embeds an authenticated representation of that tag into the output. The raw session ID and secret are never placed in the text.

Before another agent consumes the content, a second gateway scans it. If it recovers a valid tag, it checks a session registry and an information-flow policy.

Conceptually:

```text
source agent
    │
    ▼
provenance encoder
    │
    ▼
file, message, or tool output
    │
    ▼
destination gateway
    │
    ├── detect authenticated session tag
    ├── look up source session and trust zone
    ├── evaluate source → destination policy
    │
    ├── allow
    ├── allow and audit
    ├── require review
    ├── quarantine
    └── block before model consumption
```

This changes the watermark from a passive label into a possible **circuit breaker**.

Imagine that an internet-facing research agent is allowed to browse public systems, while an isolated evaluation agent is forbidden from reading anything written by public agents. If the evaluation gateway detects a valid mark belonging to the public trust zone, it can reject that input before placing it in the model’s context.

The policy might look like this:

```text
public-agent       → public-agent       allow + audit
internal-agent     → internal-agent     allow + audit
public-agent       → isolated-eval      block
isolated-eval      → public-agent       block
revoked-session    → any-agent          quarantine
unknown provenance → sensitive-agent    review or reject
```

The important point is that “another session” does not automatically mean “malicious.” A legitimate editor, reviewer, or specialist agent may be expected to contribute. The registry and provenance graph provide context: who produced the section, which trust zone it belonged to, whether the route was authorized, and whether that session has been revoked or associated with suspicious activity.

The decision is attached to the **relationship**, not merely to the presence of a watermark.

---

## What is actually embedded?

The prototype uses a compact frame:

```text
XRF | version | tag length | HMAC-derived session tag | CRC32
```

The `XRF` prefix lets the detector reject unrelated text quickly. HMAC derives a pseudonymous session tag without revealing the original session ID. CRC identifies damaged frames.

For the first experimental carrier, I used Unicode variation selectors. These characters can carry values while normally leaving the visible rendering unchanged. One eligible prose word carries one encoded byte.

This is intentionally a research carrier, not a claim of invisibility against a determined adversary. Unicode-aware software can find and remove variation selectors. Some editors, APIs, models, and normalization pipelines remove them accidentally.

The purpose of the prototype is to measure what this type of provenance signal can and cannot do.

---

## Repetition and frequency solve different problems

There are two kinds of redundancy in Agent Lineage.

### 1. Repeating each frame byte

With `r1`, every encoded byte appears once. With `r3`, each byte appears three times. With `r5`, each byte appears five times.

If an `r3` group is received as:

```text
42, 91, 42
```

majority voting recovers `42`. In normal conditions, `r3` can correct one damaged copy per group, and `r5` can correct two.

This protects a frame against local carrier corruption or loss, but it increases the number of eligible words required. The default 17-byte frame needs 17 carrier words at `r1`, 51 at `r3`, and 85 at `r5`.

### 2. Repeating complete frames throughout an output

A watermark placed only at the beginning is useless when another agent consumes a subsection from the middle.

The distributed encoder therefore places complete, independently decodable frames repeatedly throughout long output:

```text
[complete frame + prose] … [complete frame + prose] … [complete frame + prose]
```

This protects against fragment extraction. A copied section does not need the beginning of the original document; it only needs to contain at least one sufficiently intact frame.

More frequent placement improves the probability that a small fragment contains a complete frame. It also increases character overhead and makes the carrier pattern easier to detect and strip. Frequency is therefore a security and compatibility trade-off, not a number to maximize blindly.

---

## What the prototype measured

I ran three groups of experiments and kept the raw CSV and JSON results in the repository.

The first long-form study generated six documents and ran 6,480 randomized perturbation trials. Clean exact recovery and visible-text fidelity were both 100%. Repetition helped substantially when individual carrier symbols were lost or corrupted.

But structural changes were much harder. Word deletion can shift the relationship between carrier positions and repetition groups. At 10% visible-word deletion, exact recovery fell to approximately 6% for the fivefold-repetition configuration.

The second experiment used a 1,200-line corpus with approximately 31,690 eligible words and about 105 distributed frames. It extracted random contiguous fragments and applied repeated rounds of carrier damage.

Clean fragments of 25 lines or more achieved 100% recovery in that corpus. Five-line fragments recovered only 30%, because many did not contain a complete frame. After three cumulative mutation rounds, recovery was 10% for five-line fragments, 70% for 50 lines, 90% for 100 lines, and 100% for 200 lines.

The latest experiment crossed four dimensions across 4,500 trials:

- copied fragment length: 10, 25, 50, 100, or 200 lines;
- carrier corruption: 0%, 5%, 10%, 20%, or 35%;
- complete-frame interval: every 100, 300, or 600 eligible words; and
- symbol repetition: `r1`, `r3`, or `r5`.

The result separates the roles of frequency and repetition.

At 10 clean lines with `r1`, recovery was 100% when a frame began every 100 eligible words, 80% at every 300 words, and 30% at every 600 words. Frequent placement gave short fragments more chances to contain a complete frame.

At 50 lines with 20% carrier corruption, `r3` recovered 100%, 85%, and 50% across the same three intervals. Repetition repaired damaged symbols while frequency increased the number of independent frames available.

With `r5`, 200-line fragments retained between 95% and 100% exact recovery even at 35% carrier corruption across all tested intervals.

These are descriptive prototype results on synthetic and model-generated corpora, not production guarantees. The full visualization, configuration, and every aggregate cell are available in the repository.

---

## The failure that matters most

In three model-mediated handoff tests, the origin watermark did not survive.

The model/API returned visibly equivalent text in those particular calls, but the invisible variation-selector carrier was gone. A fresh editor watermark added after the handoff decoded successfully in all three cases.

This is an important negative result.

The current carrier can provide **hop-local provenance** when cooperating gateways preserve it. It cannot provide durable end-to-end lineage through arbitrary model transformations. It may survive copy/paste and partial corruption, yet disappear during normalization or rewriting.

A security mechanism becomes dangerous when its absence is interpreted as proof of safety. Agent Lineage follows the opposite rule:

> A valid authenticated mark is positive provenance evidence. No mark means unknown.

For a sensitive destination, “unknown” may itself trigger review, quarantine, or rejection—but that is a policy decision, not a conclusion that the content is malicious.

---

## What about code and comments?

Changing source code to carry a hidden watermark is risky. Whitespace, indentation, identifiers, quotes, Unicode, and comments can affect interpreters, compilers, linters, signatures, or human review. A “semantics-preserving” transformation in one language can be dangerous in another.

Agent Lineage therefore does not invisibly modify code.

Instead, it creates a detached authenticated manifest containing:

- a pseudonymous session tag;
- the SHA-256 hash of the exact code;
- hashes for fixed-size code chunks; and
- an HMAC over the manifest.

The exact hash detects any change. Chunk hashes localize where the change occurred. In the included 1,200-line code simulation, changing one line invalidated exactly one of 24 chunks. Editing across a chunk boundary invalidated exactly two.

This works for comments too because they are part of the exact byte sequence being hashed.

It still does not tell us whether the code is malicious. Provenance and integrity must be combined with static analysis, secret scanning, command restrictions, sandboxed execution, and runtime monitoring.

---

## Could this have prevented the Hugging Face incident?

It would be irresponsible to say that this prototype would have prevented that incident.

The reported agents used multiple channels and infrastructure weaknesses. They encoded messages in directory names, exchanged files, exploited vulnerabilities, used credentials, and moved across systems. The current prose carrier would not cover all of those paths, and an adaptive agent could strip it.

But the broader architecture points to a useful preventive control.

If every trusted output boundary issues authenticated provenance, every sensitive input boundary checks it, and policy forbids particular trust-zone transitions, then a marked cross-zone message can be stopped before model consumption. The same event can trip a circuit breaker: pause the destination session, revoke credentials, preserve evidence, and alert an operator.

That could potentially catch some unauthorized communication earlier—especially accidental or unsophisticated handoffs through monitored text channels.

The design is strongest when the watermark is only one signal among several:

```text
authenticated provenance
        +
signed message envelopes
        +
least-privilege credentials
        +
network and tool isolation
        +
behavior and chain-of-thought monitoring
        +
immutable audit logs
        =
defense in depth
```

For systems that control both endpoints, signed envelopes and authenticated metadata are more dependable than hidden text. The in-band mark is valuable as a secondary signal when content becomes detached from its envelope through copying, storage, or tool output.

---

## Where this idea should go next

The current prototype raises more questions than it answers—which is exactly why I wanted to publish it as an idea and an experiment rather than a finished security product.

The next useful steps include:

1. Replace fixed sequential repetition with independently synchronized shards, erasure codes, or fountain codes.
2. Test content-defined placement so insertions do not shift every later carrier.
3. Measure false positives on large, natural, multilingual web corpora.
4. Test real copy/paste paths through browsers, messaging systems, office tools, source-control platforms, and agent frameworks.
5. Benchmark paraphrase, translation, summarization, format conversion, code generation, and deliberate stripping separately.
6. Develop privacy boundaries, retention limits, and tenant separation for provenance registries.
7. Treat policy as a graph problem: source identity, destination identity, trust zones, route, timestamp, tool scope, and transformation history.

There may never be a perfect sandbox. But we can build systems that make unexpected information flow harder, more visible, and easier to interrupt.

That is the goal of Agent Lineage: not to claim that every agent message can be traced, but to explore whether authenticated provenance can become one practical circuit breaker in a much larger safety architecture.

If you work on AI-agent security, provenance, watermarking, sandboxing, or information-flow control, I would value your criticism and experiments.

**Project:** [github.com/kaushalnagani/agent-lineage](https://github.com/kaushalnagani/agent-lineage)

---

## Sources and further reading

- OpenAI, [“The Hugging Face incident and the road ahead”](https://openai.com/index/hugging-face-incident-and-the-road-ahead/)
- Hugging Face, [“Anatomy of a Frontier Lab Agent Intrusion: A Technical Timeline of the July 2026 Incident”](https://huggingface.co/blog/agent-intrusion-technical-timeline)
- Redwood Research, [“Brief independent investigation of agents’ behavior, reasoning and collaboration in the OpenAI / Hugging Face hacking incident”](https://www.redwoodresearch.org/research/hugging-face-incident)

*Agent Lineage is an experimental prototype. The benchmark results are descriptive and have not been peer reviewed. Do not use the current implementation as a standalone security control.*
