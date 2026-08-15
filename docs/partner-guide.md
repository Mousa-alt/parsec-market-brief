# Partner guide

Everything the partner needs to work in this repo, connect an account, and know
what the tool will and will not do. No code required to read this.

---

## 1. Your space in this repo

You and your agent have **write access**. Create branches and open pull requests
freely — that is the intended way to work here, not an exception.

- **`main` is protected.** It only changes through a pull request that passes
  review. Nobody pushes to it directly, including the other owner.
- **An automated reviewer runs about every four hours** over every open PR from
  your agent. It checks the change against the acceptance criteria in
  [ROADMAP.md](../ROADMAP.md) and against the guardrails, and it runs the test
  suite.
- **If it passes, the PR merges automatically.** There is no human gatekeeping
  on clean work — you do not wait on anyone's schedule.
- **If it requests changes**, the comments say exactly what to fix. Push the fix
  to the same branch; the reviewer picks it up on its next pass and re-reviews.
- **Radical experiments: fork the repo.** One click on GitHub gives you a full
  private copy where nothing is protected and nothing is reviewed. Sync it with
  upstream whenever you want, and open a PR back here only for the parts that
  proved out.
- **Disagreement about scope is not a code problem.** If you think a direction
  in the roadmap is wrong, open a GitHub Issue in the format at the bottom of
  [ROADMAP.md](../ROADMAP.md#how-to-propose-a-change) rather than writing code
  against it. That is the cheaper argument to have.

---

## 2. What's already specced for you

Two issues are written up and ready to be implemented — your agent can pick up
either one, through the PR flow above.

- **Issue #5 — per-recipient briefs.** The brief stops being one shared document
  and becomes one per holder. Your copy becomes **US-only automatically**: the
  brief follows each holder's portfolio, so a US-only book produces a US-only
  brief without anyone configuring that specially.
- **Issue #6 — IBKR connection.** The read-only account link described in the
  next section, so your positions feed the brief instead of being typed in by
  hand.

---

## 3. Connect your IBKR account

Read-only, about ten minutes, works on a phone or desktop browser.

1. Log in at **interactivebrokers.com** and open the **Client Portal**.
2. Go to **Menu → Performance & Reports → Flex Queries**.
3. In the **Activity Flex Query** panel, press **+** to create one.
   - Name it something plain, e.g. `brief-portfolio`.
   - Add these sections: **Cash Report**, **Cash Transactions**,
     **Open Positions**, **Trades**. Inside each one, choose **Select All**.
   - Set **Format** to **XML** and **Period** to **Last 30 Calendar Days**.
   - Save. Then note the **Query ID** — the ⓘ icon next to the query name shows
     it.
4. In the right-hand panel, **Flex Web Service Configuration**, press the ⚙:
   - Enable the service.
   - **Expire After: 1 Year**.
   - Leave the **IP restriction blank**.
   - Press **Generate New Token** and copy the token.
5. Give the **Query ID** and the **token** to **your agent** — nobody else. They
   live in *your own* config or environment variables.

> **Tokens never go into this repo.** Keep them in your own config/env only.
> (Issue #6 adds a test that auto-rejects any commit containing a token
> pattern — until that lands, the rule is manual: paste tokens nowhere but
> your own machine.)

---

## 4. Why this is safe

The Flex service is IBKR's **reporting** API. Concretely:

- It can **only download statements**. It **cannot place trades**, **cannot
  withdraw**, **cannot transfer funds**, and **cannot change account settings**.
- Withdrawals require a Client Portal login plus **2FA on your own device** —
  a Flex token is not a path to money leaving the account.
- The token is **revocable instantly** from the same ⚙ screen you created it on.
- **"Cash Transactions" is a statement page** — a *list of past* deposits and
  withdrawals. Selecting it grants the ability to *read that history*, not to
  move anything.

This exact setup is already live on the other owner's account — connected today
and verified pulling balances and positions only.

---

## 5. What "customized to you" means

Once Issues #5 and #6 land:

- **Your daily brief covers your portfolio**, pulled from your IBKR account —
  your US names, US macro, nothing else cluttering it.
- **The other owner's brief covers his tri-market book** (US, Tadawul, EGX).
- Same engine, same guardrails, two personal briefs.

Until then, you receive the shared brief. Nothing breaks in the meantime.

---

## 6. House rules recap

- **Monitoring only.** The brief never says buy, sell, or hold — the research
  behind that decision is in
  [docs/research/evidence-review.md](research/evidence-review.md).
- **One model composes.** No debate panels, no consensus rounds.
- **Additive pull requests.** Add, don't strip: existing comments, tests, and
  documentation stay unless removing them *is* the point of the PR.
- **Every number carries its source and its as-of date.** A number without
  provenance does not ship.

---

Not investment advice.
