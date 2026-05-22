# Multi-Agent Evaluation Context

This document defines how benchmark files in this directory are used by the
automated evaluation framework.

## Principles

*   Every scenario must be an isolated e2e user journey, it must not depend on
    any existing assets in the GCP project. However, the scenarios may declare
    files to be present in the agent's working directory through assets.

## 1. The Roles (Who is Who)

| Persona                 | Definition             | Operational Boundary      |
| :---------------------- | :--------------------- | :------------------------ |
| **User Simulator**      | Acts as a PM or QA     | Can ONLY talk to the      |
:                         : Tester. It uses the    : Agent-Builder-Agent. Has  :
:                         : `context` and `steps`  : no access to GCP or the   :
:                         : keys to drive the      : Target Agent.             :
:                         : conversation.          :                           :
| **Agent-Builder-Agent** | **The Subject Under    | Uses its capabilities and |
:                         : Test (SUT).** A coding : the referenced skills to  :
:                         : agent (e.g., Antigravity) : issue API calls to build  :
:                         : tasked with building a : the Target Agent.         :
:                         : solution.              :                           :
| **Target Agent**        | The "Product" being    | Never talks to the        |
:                         : built. This is the     : Simulator. Responds to    :
:                         : actual CES (CXAS)      : API calls from the        :
:                         : resource in GCP.       : Builder.                  :
| **Scorer**              | An automated Auditor.  | Sees the full trace: Chat |
:                         : It evaluates the run   : history + Raw API         :
:                         : using the criteria in  : Request/Response logs.    :
:                         : the `rubric` key.      :                           :

## 2. Anatomy of a Benchmark File (.yaml)

Every benchmark file in this directory serves three purposes:

### A. The Scenario (Instructions for the User Simulator)

This is defined by the `context` and `steps` keys in the YAML file. The **User
Simulator** reads this to know which persona to adopt and what goals to achieve.
By including the technical requirements here, we test the **bundled skills**
(Reference Guide) together with the **Agent-Builder-Agent's base capabilities**.

### B. The Reference Guide (Manual for the Builder)

While not a distinct YAML key, the technical recipes, API constraints, and code
snippets that guide the Builder are typically included within the `context` or
`steps` strings. The evaluation verifies if the Builder can accurately apply
these specific instructions to reach the desired state.

### C. The Rubric (Criteria for the Scorer)

The **Scorer** uses the list of criteria in the `rubric` key to grade the
interaction. Because the Scorer is an "Auditor," the rubric criteria should
verify both the conversation and the **CES API calls** visible in the traces.

## 3. Interaction Logic

-   **Driving**: The Simulator prompts the Builder.
-   **Proxy Testing**: To verify work, the Simulator may ask the Builder to
    "test the bot." The Builder must call `:runSession` or `executeTool` on the
    Target Agent and report back.
-   **Scoring**: The Scorer audits the transcript. It checks if the Builder's
    summary to the user matches the **Target Agent's actual replies** visible in
    the API responses.

## 4. Scenario Validation

To ensure that scenarios are correctly formatted and do not cause failures
during evaluations, a validation test is available.

You **MUST** run this test after making any changes to the scenario files or
adding new ones:

```bash
python3 scenarios/validate_scenarios.py
```

This test verifies that: - The file is a valid YAML file. - All required keys
(`name`, `context`, `steps`, `rubric`) are present. - The rubric items contain
the required fields (`criteria`, `perfect`, `good`, `failed`).
