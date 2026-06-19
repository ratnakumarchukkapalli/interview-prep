# Section 16: LLD, SOLID Principles & Design Patterns

> **Purpose:** Low-Level Design (LLD) interview prep — SOLID principles and design patterns, anchored to your actual codebase.
> **Frame:** You didn't study these patterns — you built them in production. In an interview, you name them and point to where they live.

---

## Part 1 — SOLID Principles

SOLID is five object-oriented design principles that make code maintainable, extensible, and testable. Interviews ask you to define them AND give an example from your work.

### S — Single Responsibility Principle (SRP)

**Definition:** A class should have one reason to change. One job, one owner.

**Your examples:**
- `base_agent.py` — runs the agentic loop only. No routing logic, no auth, no tool implementation.
- `orchestrator.py` — routing logic only. No agent code.
- `auth_middleware.py` — JWT validation only. No business logic.
- Each agent (Datadog, K8s, Cert) — one domain only.

**How to spot a violation:** A class named `UserManager` that also sends emails, validates passwords, AND writes audit logs. It has 4 reasons to change.

---

### O — Open/Closed Principle (OCP)

**Definition:** Open for extension, closed for modification. Add new behaviour without changing existing code.

**Your example:**
- Adding a new agent (e.g., `IncidentAgent`) requires: create a new file, register in `ChatService`, add keywords to `orchestrator.py`. **No changes to `BaseAgent`, no changes to existing agents.**
- Adding a new K8s tool: add schema + function in `k8s_tools.py`, register in `K8sAgent._register_tools()`. No changes to the agentic loop.

**How to spot a violation:** Every time you add a feature, you modify a switch/if-else chain inside a core class.

---

### L — Liskov Substitution Principle (LSP)

**Definition:** Subclasses must be substitutable for their parent without breaking the program.

**Your example:**
- `DatadogAgent`, `K8sAgent`, `CertAgent` all extend `BaseAgent`. Any of them can be passed to `ChatService` in place of the abstract `BaseAgent` — the loop still works.
- If a subclass threw an exception where the parent returns a string, that violates LSP.

---

### I — Interface Segregation Principle (ISP)

**Definition:** Don't force clients to depend on interfaces they don't use.

**Your example:**
- `K8sAgent` only receives K8s tool schemas — 17 tools. It doesn't see Datadog tools and has no interface to them.
- `DatadogAgent` doesn't know K8s tools exist.
- Each agent's `registered_tools` is its own interface — tightly scoped.

**Why this matters for LLMs:** When you attach 38 tools to one agent, the model's tool-selection accuracy degrades. ISP applied at the agent layer is why 3 specialized agents outperform one mega-agent.

---

### D — Dependency Inversion Principle (DIP)

**Definition:** High-level modules should not depend on low-level modules. Both should depend on abstractions.

**Your example:**
- `BaseAgent` depends on `AnthropicTRClient` (abstraction), not on `anthropic.Anthropic` directly. Swapping the client (e.g., to a mock for testing) doesn't require changing `BaseAgent`.
- `ChatService` depends on the `BaseAgent` interface, not on `K8sAgent` or `DatadogAgent` directly.

---

## Part 2 — Design Patterns from Your Code

Design patterns are proven solutions to recurring design problems. Three categories: Creational (how objects are created), Structural (how objects are composed), Behavioural (how objects communicate).

---

### Creational Patterns

#### Singleton

**Definition:** Only one instance of a class exists; provide a global access point.

**Your example:** `SessionManager` — created once at FastAPI startup, shared across all requests. Holds the TTLCache of all user sessions.

```python
# In app startup
session_manager = SessionManager(max_sessions=1000, ttl_seconds=3600)
# All routes use the same instance
```

**When to use:** Shared resources — caches, DB connection pools, config objects. One instance avoids duplication of expensive setup.

**Interview trap:** "Singleton is bad because it makes testing hard" — correct response: "Dependency injection solves that. Pass the singleton as a parameter rather than accessing it as a global. Tests can inject a mock."

---

#### Factory (Method / Abstract Factory)

**Definition:** Define an interface for creating an object; let subclasses or configuration decide which class to instantiate.

**Your example (implicit Factory in `ChatService`):**
```python
def get_agent(routing_result: str) -> BaseAgent:
    if routing_result == "datadog":
        return DatadogAgent(config)
    elif routing_result == "k8s":
        return K8sAgent(config)
    elif routing_result == "cert":
        return CertAgent(config)
```

The caller (`ChatService`) doesn't know which concrete agent it gets — it just calls `.handle()`.

**When to use:** When the type of object to create depends on runtime conditions and you want to decouple creation from usage.

---

#### Builder

**Definition:** Construct a complex object step by step. Separate construction from representation.

**Your example:** Claude API message construction. Each iteration of the agentic loop builds up the `messages` list:

```python
messages = []
messages.append({"role": "user", "content": query})          # Step 1
messages.append({"role": "assistant", "content": tool_use})   # Step 2 (after iteration 1)
messages.append({"role": "user", "content": tool_result})     # Step 3
# ... repeat until end_turn
```

The final `messages` payload is built incrementally. A strict Builder pattern would wrap this in a `MessageHistoryBuilder` class.

---

### Structural Patterns

#### Decorator

**Definition:** Add behaviour to an object by wrapping it — without modifying the original class.

**Your example:** FastAPI middleware stack.

```
Request →
  [RateLimitMiddleware]      ← wraps the handler
    [AuthMiddleware]         ← wraps the handler
      [GuardrailMiddleware]  ← wraps the handler
        [actual route handler]
```

Each middleware wraps the next. The route handler doesn't know it's being rate-limited or auth-checked. Adding a new middleware doesn't touch existing ones.

**Real-world analogies (if interviewer asks):** Coffee shop drinks — a plain coffee is decorated with milk, then sugar, then whipped cream. Each adds behaviour without changing the base.

---

#### Facade

**Definition:** Provide a simplified interface to a complex subsystem.

**Your example:** `correlate_infra_with_services` — hides PG + RMQ + OpenSearch + Datadog complexity behind a single function call.

```python
# Without Facade — caller must orchestrate 4 backends:
pg_result = query_postgresql_diagnostics(env)
rmq_result = query_rabbitmq_diagnostics(namespace)
os_result = search_opensearch(env)
dd_result = query_datadog_error_rates(env)
# ... then combine + summarize

# With Facade:
platform_health = correlate_infra_with_services(namespace, env)
```

Claude calls one tool and gets a structured answer. The fan-out complexity is hidden.

---

#### Adapter

**Definition:** Convert the interface of a class into another interface that clients expect.

**Your example:** `AnthropicTRClient` — adapts the TR CIAM token exchange chain into the same interface as a plain `anthropic.Anthropic` client. The rest of the code calls `.messages.stream(...)` — it doesn't know about CIAM or the Common Token API.

---

### Behavioural Patterns

#### Template Method

**Definition:** Define the skeleton of an algorithm in a base class; let subclasses fill in specific steps.

**Your example:** `BaseAgent` is the textbook Template Method.

```python
class BaseAgent:
    async def handle(self, message, history):   # ← THE TEMPLATE — don't override this
        system_prompt = self.get_system_prompt()  # ← override in subclass
        tools = self.registered_tools             # ← set in _register_tools()
        for iteration in range(MAX_ITERATIONS):
            response = await self.call_claude(system_prompt, tools, history)
            if response.stop_reason == "end_turn":
                return response.text
            # ... execute tool, loop back

    def get_system_prompt(self) -> str:
        raise NotImplementedError  # subclass must implement

    def _register_tools(self):
        raise NotImplementedError  # subclass must implement
```

`DatadogAgent`, `K8sAgent`, `CertAgent` each implement `get_system_prompt()` and `_register_tools()`. The loop itself never changes.

---

#### Strategy

**Definition:** Define a family of algorithms, encapsulate each, and make them interchangeable.

**Your example:** `ModelSelector` — the algorithm for "which model to use" is swappable at runtime based on config and query complexity.

```python
# The "strategy" is which model to select
class ModelSelector:
    def select(self, query: str, token_count: int) -> str:
        if token_count > 150_000:
            return "claude-sonnet-4-6"   # cost guard
        if self._is_complex(query):
            return self.config.default_complex_model   # Opus 4.7
        return "claude-sonnet-4-6"       # medium/simple
```

The strategy (how to pick a model) is separate from the caller (the agentic loop).

---

#### Observer

**Definition:** When one object changes state, its dependents are notified automatically.

**Your example (implicit):** OTEL spans in the agentic loop. The `agent_span` context manager fires telemetry events (to Datadog via OTEL) as side effects of tool execution and LLM calls — without the loop code caring about observability.

---

## Part 3 — LLD Interview Format

LLD rounds give you a problem and ask you to:
1. Identify the entities (classes/objects)
2. Define relationships (has-a, is-a)
3. Apply appropriate patterns
4. Draw a class diagram

**Using your own system as the practice problem:**

**Problem:** "Design an AI operations assistant"

**Entities:**
- `FastAPIApp` — entry point, middleware stack
- `AuthMiddleware`, `RateLimitMiddleware`, `GuardrailMiddleware` — Decorator chain
- `SessionManager` — Singleton, holds TTLCache
- `Orchestrator` — Router, keyword scoring
- `BaseAgent` (abstract) — Template Method
- `DatadogAgent`, `K8sAgent`, `CertAgent` — concrete strategies
- `ModelSelector` — Strategy
- `CIAMTokenClient` — Cache-Aside, handles auth
- `AnthropicTRClient` — Adapter over CIAM chain

**Relationships:**
- `FastAPIApp` has-a `SessionManager` (Singleton)
- `FastAPIApp` has-a `Orchestrator`
- `Orchestrator` creates-a `BaseAgent` subclass (Factory)
- `DatadogAgent`, `K8sAgent`, `CertAgent` is-a `BaseAgent` (inheritance)
- `BaseAgent` has-a `AnthropicTRClient`
- `BaseAgent` has-a `ModelSelector`
- `FastAPIApp` has-a middleware chain (Decorator)

**Patterns applied:**
- Template Method: `BaseAgent`
- Strategy: `ModelSelector`
- Singleton: `SessionManager`
- Factory: agent creation in `ChatService`
- Decorator: middleware stack
- Facade: `correlate_infra_with_services`
- Cache-Aside: `CIAMTokenClient`

---

## Part 4 — One-Liner Definitions to Memorise

| Pattern | One-liner |
|---------|-----------|
| **Singleton** | One instance, global access point — shared resources like caches and config |
| **Factory** | Decouple object creation from usage — caller doesn't know the concrete type |
| **Builder** | Construct a complex object step by step — useful for objects with many optional parts |
| **Decorator** | Wrap an object to add behaviour without modifying it — your middleware stack |
| **Facade** | Single simplified interface over a complex subsystem — your cross-subsystem fan-out tool |
| **Adapter** | Convert one interface to another — your CIAM token client wrapping the Anthropic interface |
| **Template Method** | Base class defines the algorithm skeleton; subclasses fill in specific steps — your BaseAgent |
| **Strategy** | Swappable algorithms at runtime — your ModelSelector |
| **Observer** | Notify dependents on state change — your OTEL telemetry hooks |
| **SRP** | One class, one reason to change |
| **OCP** | Extend without modifying existing code |
| **LSP** | Subclasses must be substitutable for their parent |
| **ISP** | Don't force clients to depend on interfaces they don't use |
| **DIP** | Depend on abstractions, not concretions |

---

*Created: 2026-06-11. Cross-reference: Scaler Modules 9-11 (OOP, SOLID, Design Patterns), `15-system-design-cs-vocabulary.md`.*
