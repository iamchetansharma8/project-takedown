# How we work in this repo

Small repo, one person, but the history is written for whoever reads it next.

Most of the churn here will be in `rules.py` — the judging weights change
constantly by design. **Why a weight changed matters more than what changed**,
because the number itself is visible in the diff and the reasoning isn't.

---

## Every change goes through a branch and a pull request

Yes, even alone. The point is reading your own diff before it lands.

```bash
git checkout -b describe-the-change
# ... work ...
git add -p                      # stage deliberately, not with -A
git commit
git push -u origin describe-the-change
gh pr create
gh pr diff                      # read it properly before merging
gh pr merge --rebase --delete-branch
```

`--rebase`, not `--squash` — squashing throws away the individual commits,
which defeats the point of making them atomic.

Branch names: lowercase, hyphens, describe the change.
`add-telegram-collector`, `fix-safety-backfire-rule`.

---

## Commit messages

**Subject:** imperative mood, under about 50 characters, no full stop.
Finish the sentence *"If applied, this commit will…"*

**Body:** wrap at 72 characters. Explain **why**, and what evidence prompted it.
Skip the body only when the subject genuinely says everything.

Plain English, no `feat:` / `fix:` prefixes. Someone non-technical may read
this repo.

### Good

```
Stop spread from inflating harm on benign content

A film trailer with 500k views scored maximum harm purely because it
was travelling fast. Spread now multiplies content harm instead of
adding to it, so harmless content scores zero regardless of reach.

Floor of 0.5 keeps a catastrophic item nobody has seen yet from
dropping off the list entirely.
```

```
Exempt safety harm from the low-reach backfire penalty

A leaked home address with 352 views was marked "do not touch"
because almost nobody had seen it. That logic protects reputation,
not people. Low reach is exactly why you remove an address quietly,
before anyone notices.
```

### Bad

```
fix                       - fix what
updated rules.py          - the diff already says that
various improvements      - which ones, and why
Fixed the scoring bug.    - past tense, vague, trailing full stop
```

---

## One logical change per commit

Never mix a rules change with a refactor. If you tuned a weight *and* renamed a
function, that's two commits. When a weight turns out to be wrong later, you
want to revert the weight without losing the rename.

---

## Rules changes carry their evidence

Every change to `rules.py` should answer three things in the body:

1. What behaviour changes
2. What made you notice — which row, which video, which score
3. What you expect to happen to the ranking as a result

Write point 3 **before** running it. That's how you find out whether you
understand your own system.

---

## Never commit

- Anything under `data/` — real people's content. It's gitignored; keep it that way
- API keys, `.env`, anything with a token in it
- Real clients' names or context files, once there are real clients
