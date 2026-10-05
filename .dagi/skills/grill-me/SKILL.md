---
name: grill-me
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
triggers: grill, /grill, /grill-me, stress-test this, grill my plan, grill my idea
---

# grill-me

Interview me relentlessly about every aspect of this until we reach a shared
understanding. 

Ask the questions **one at a time**, waiting for feedback on each question before
continuing. Asking multiple questions at once is bewildering.

If a fact can be found by exploring the environment (filesystem, tools, etc.),
look it up rather than asking me. The decisions, though, are mine — put each one
to me and wait for my answer.

Do not act on it until I confirm we have reached a shared understanding.

## Design and Decisions
If the topic is about a design, task, or decision that user is trying to make, walk down each branch of the decision tree, resolving dependencies between decisions one-by-one.

## Queries
If the topic is a question, ask clarifying questions to understand the context and scope of the question. Identify what the user knows, what they don't know, and what they need to know to answer the question. 

## Closing
When shared understanding is reached, produce a closing summary covering:
- what was tested
- what held up under pressure
- what was weak, missing, or unresolved
- concrete actions before proceeding

When invoked as the clarification stage of `enter-workflow`, return the closing
summary so the workflow can proceed to the next stage. When invoked directly via
`/grill-me`, return the closing summary and suggest appropriate next steps
(e.g. `write-plan`, `/deliver`, or direct implementation). Do not launch planning
or implementation automatically.
