# Product Requirements Document: Triage & Specialist

## 1. Overview
This PRD specifies a minimal virtual agent system to test the evaluation
lifecycle. It consists of a Triage Agent and a Billing Specialist Agent.

## 2. Agents

### TriageAgent (Root)

- **Role**: Initial contact for users.
- **Behavior**:
  - Greets the user.
  - Calls the tool `check_billing_status`.
  - If the tool returns `"DELINQUENT"`, transfers to `BillingSpecialist`.
  - Otherwise, states everything is fine.

### BillingSpecialist

- **Role**: Handles billing issues.
- **Behavior**:
  - Responds: `"Welcome to Billing. I see you have an overdue balance."`

## 3. Tools

### `check_billing_status`

- **Role**: Checks billing status.
- **Implementation**: Mock to always return `"DELINQUENT"`.

## 4. Golden Conversation (For Evaluation)
1. **User**: "I need help with my account."
2. **TriageAgent**: (Calls `check_billing_status` -> `"DELINQUENT"`)
3. **TriageAgent**: (Transfers to `BillingSpecialist`)
4. **BillingSpecialist**: "Welcome to Billing. I see you have an overdue balance."
