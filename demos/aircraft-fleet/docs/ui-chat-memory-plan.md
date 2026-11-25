# Plan: Starter questions, follow-up links, and a memory view in the fleet UI

## Summary

The UI opens with a single starter question, gives no hint of what to ask
next, and shows only fleet evidence. After this plan, the welcome panel
offers a dropdown of starter questions. Each answer ends with a few
suggested follow-up questions that you can click to ask. The graph panel
gets a second view that shows the memory the supervisor recalled for the
question. Memory recall also becomes truly per user, so one user's recalled
facts never reach another user.

- **Removed:**
  - The single starter button.
- **Fixed:**
  - Memory entity and fact search spans every user. A signed-in user can recall entities and facts learned from another user's conversations. It will search only the asking user's memory.
- **Added:**
  - A dropdown of about six starter questions.
  - Suggested follow-up questions under each answer, sent as their own stream event.
  - A Memory view beside the current evidence view, showing the entries memory recalled for the question.
  - A fork release of neo4j-agent-memory that scopes entity and fact search to a user and exposes the recalled entries.
  - A link from each stored fact to the user who stored it.

## Facts this plan rests on

Each of these was checked in the code on 2026-11-24.

- **Starter:** `ui/static/index.html` has one starter button. `app.js` sends a longer prompt for it that asks for the event IDs the evidence graph needs.
- **Recall is hidden:** The Strands session manager in neo4j-agent-memory searches long-term memory when a user message arrives. It prepends the hits to the message as a plain text block. It keeps no record of the hits, so the caller cannot see which entries were recalled.
- **Recall is not per user:** The preference search is limited to the user. The entity and fact searches take no user and search every user's entries. The library's `multi_tenant` setting covers only preferences.
- **Entities and facts have different owners:** An entity reaches its user through the messages that mention it, and each conversation records its user. A fact is a standalone node with no link to any user, message, or conversation.
- **The fleet and facts:** The supervisor neither stores nor recalls facts today. Fact recall is off by default, and the supervisor leaves it off.
- **What is per user today:** Conversation history is per session, and the hosted UI's session ID is a hash of the user and the browser session. Preferences are linked to the user.
- **Memory database:** Memory is a separate Neo4j database. The UI has no login for it, and the hosted UI's role can read only the fleet login secret.
- **Fork releases:** The fleet fork is neo4j-partners/agent-memory, branch `fleet-fixes`. The supervisor pins `0.8.0+fleet.10` from a GitHub prerelease wheel.

## Decisions

All answered on 2026-11-24.

- **Starters are a dropdown.** About six questions cover maintenance, operations, a manual or limit question, and one question that spans both domains. Each prompt asks for the IDs the evidence graph needs. The hydraulic question stays first.
- **Follow-ups come from a separate model call.** After the answer, the supervisor makes one small structured call that returns about three follow-up questions, and sends them as their own stream event. The UI shows them as links under the answer, and a click sends that question. This works locally and in the cloud, and the UI's permissions stay the same. Neither memory nor the CLI output changes. Asking the supervisor to end its answer with a list is dropped, because the parsing would be fragile and the list would be stored in memory. Fixed follow-ups per specialist are dropped too, because they would not relate to the answer.
- **The memory view shows what was recalled for this answer.** The supervisor sends the recalled entries in the stream. The UI then needs no memory login, and the hosted role keeps its single secret. A view of everything memory holds for the user is dropped. It would need the memory login in the UI and a second secret on the hosted role, and every query would have to be scoped to the user.
- **The scope fix goes in the fork.** Entity and fact search gains a way to search only one user's entries, and the supervisor passes the user. This fixes the root cause. Documenting the gap is dropped, because something a user says about themselves could still reach other users. Turning off entity and fact recall is dropped too, because memory would lose most of what it recalls.
- **Facts get a user link.** When a caller passes a user, storing a fact also links it to that user, the same way a preference is linked. A fact search with a user returns only that user's facts. Without a user, storing and searching behave as today. This is the only way to isolate facts, because a fact has no other path to a user. Leaving fact search unscoped is dropped, because another app that recalls facts would still leak them. A scoped search that always returns nothing is dropped too, because it would hide facts without saying so. Facts stored before the change have no owner, so the memory database is reset after the release.
- **The fork exposes the recalled entries.** The session manager keeps the entries it last recalled, with their IDs and types, and the supervisor reads them. The view then shows exactly what the model saw. Having the supervisor repeat the search is dropped. It would cost an extra embedding and vector query per question, and its results could drift from what the model saw.

## Deliberately not doing

- **No memory login in the UI.** The UI never connects to the memory database.
- **No browsing or editing of memory.** The view shows one question's recall, read only.
- **No other change to what memory stores or extracts.** The fact link is the only storage change. Extraction stays the same.
- **No follow-ups in the CLI.** The CLI ignores the new event.
- **No change to the hosted UI's stack or role.**

## Where to look

- **Starter and follow-up links:** `ui/static/index.html` and `ui/static/app.js`.
- **Stream events:** `fleet_supervisor/core/events.py`, and the event relay in `ui/server.py`.
- **Memory recall:** the Strands session manager and its retrieval module in the fork, and `fleet_supervisor/core/memory.py`.
- **Evidence views:** `ui/static/graph.js`, and the graph panel in `index.html`.

## Assumptions

- The fork release follows the fleet.N pattern. Each push, tag, and release gets its own approval.
- The user granted a one-time exception to the release-age rule for fleet.11 on 2026-11-24. The supervisor relocks onto it as soon as it is released. The exception covers only fleet.11.
- Local runs keep the `anonymous` user, so all local runs share one memory, as today.

## Risks

- **Scoping entities:** Entities have no direct owner today. The fork must find each entity's user through the messages it was extracted from, and that query must stay fast.
- **Shared entries:** Scoping decides which entities and facts a user recalls, not what they say. An entity two users mention is one node, and its description can hold text extracted from the other user's conversation. A deduplicated fact is one node too, so one user's write can change the object another user sees. The user accepted this for fleet.11 on 2026-11-24. For the fleet, the shared entities are mostly aircraft, systems, and faults.
- **Scoped recall depth:** A scoped search asks the index for ten candidates per hit and then keeps the user's own. A user who owns a small share of the nearest entries can get fewer hits than the limit. That is fine for a few demo users.
- **Follow-up latency:** The follow-up call runs after the answer, so the links appear about a second after it. A failed call must never fail the answer.
- **Stream compatibility:** Older UIs and the CLI must ignore the new event types.

## Phase 1: Starter dropdown

**Status:** Complete. Built as bd6ec11 and merged to local main in 56678af on 2026-11-24. It is not pushed.

**Validation:** On the merge, 478 Python tests pass and 1 is skipped, and the 9 UI tests pass. A local run on 2026-11-24 asked all six starters through the UI's chat route against the local supervisor. Each one completed and drew graph evidence, from 13 to 50 nodes for its first graph query. A headless Chrome check against a stub chat route confirmed the keyboard and screen reader behavior and the disabled state.

**Outcome:** The welcome panel lists about six starter questions in a dropdown, and choosing one asks it.

- [x] The dropdown replaces the button, works from the keyboard and with a screen reader, and is disabled while a question runs.
- [x] Each prompt asks for the IDs the evidence graph needs.
- [x] Tests cover the list, and the READMEs name the dropdown.

**Done when:** The tests pass, and each starter shows graph evidence in a local run.

## Phase 2: Follow-up questions

**Status:** Complete. Built as 0b35f8d and merged to local main in 56678af on 2026-11-24. It is not pushed.

**Validation:** The same local run returned three follow-up questions for every starter, each about the answer's aircraft or faults. No follow-up call failed or timed out, so Haiku 4.5 access works in the account. A headless Chrome check against a stub chat route confirmed the links render as text, send their question, and are disabled during a run.

**Notes:** Some follow-ups ask for data the graph does not hold, such as oil analysis results or vibration frequency signatures after the manual starter.

**Outcome:** Each answer ends with about three follow-up links, and clicking one asks it.

- [x] The supervisor sends a follow-up event after the answer, from one small structured model call.
- [x] A failed or slow follow-up call drops the links and leaves the answer intact.
- [x] The UI shows the links under the answer and disables them while a question runs.
- [x] The CLI and older clients ignore the event.
- [x] Tests cover the event, the failure path, and the links.

**Done when:** The tests pass, and a local run shows follow-up links that relate to the answer.

## Phase 3: Fork release with user-scoped search and exposed recall

**Status:** Complete. Released on 2026-11-24 as python-v0.8.0+fleet.11, a prerelease on fleet-fixes at 779555a6. It is three commits on fleet.10 (c3283c36), so it keeps `Neo4jConfig.auth_manager`. On that commit, the fork's checks pass, 3155 unit tests pass, and 624 integration tests pass, including 14 new two-user isolation tests. The downloaded wheel's sha256 is 525f884b50fee3a46e19a2c68acde34e76d72ba4390bf30218ace75df624cdb4.

**Outcome:** A fleet.11 prerelease lets a caller limit entity and fact search to one user and read the entries the session manager last recalled.

- [x] Entity and fact search can be limited to one user's entries. Without a user, it behaves as today.
- [x] Storing a fact with a user links the fact to that user. Without a user, it stores the fact as today.
- [x] The Strands session manager passes its user to every recall search.
- [x] The session manager keeps the entries it last recalled, with their IDs and types, for the caller to read.
- [x] Fork tests cover both users' isolation and the recalled entries.
- [x] The push, the tag, and the prerelease each get a separate approval.

**Done when:** The fork's tests pass, and the prerelease wheel is published.

## Phase 4: Supervisor on fleet.11, and the Memory view

**Status:** Pending. It waits for Phase 3. The age exception for fleet.11 is approved.

**Outcome:** Recall is per user, and the graph panel shows a Memory view of what was recalled.

- [ ] The supervisor pins fleet.11 and passes the user to recall.
- [ ] The supervisor sends the recalled entries as a stream event.
- [ ] The graph panel has two views, current evidence and memory, and the UI switches between them.
- [ ] A question with no recall shows an empty Memory view with a short note.
- [ ] Tests cover the event, both views, and that one user's recall holds no other user's entries.

**Done when:**

- The tests pass.
- A local run shows recalled entries in the Memory view.
- After a redeploy, two signed-in users see only their own recalled entries.

## Phase 5: Reset both databases and rebuild

**Status:** Pending. It waits for Phase 4, so the supervisor runs on fleet.11 both locally and in the cloud before the reset.

**Outcome:** The fleet graph and the memory database hold only data built under fleet.11, so every stored fact has an owner.

- [ ] Delete every node, relationship, index, and constraint in the memory database. The instance, its login, and its secret stay.
- [ ] Rebuild the fleet graph with `./setup.sh`, which cleans and loads it. The instance, the `fleet_reader` user and its role, and the secret stay.
- [ ] The pipeline's verify step passes.
- [ ] Each reset gets its own approval, naming the instance it deletes from.

**Done when:**

- The pipeline verify passes.
- After a hosted question from each of two users, each user's facts and entities link only to that user.
- The deployed supervisor and the hosted UI answer the starter questions.

## Completion criteria

- Every phase's checklist is done or explicitly deferred.
- No `.env`, credentials, or secret values are committed or printed.
- The hosted UI's stack and role are unchanged.
