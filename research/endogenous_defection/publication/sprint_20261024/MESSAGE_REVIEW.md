# Seller-message evidence review

Status: mechanical extraction completed; selected examples reviewed by the assistant. Exhaustive semantic coding and independent review remain pending. Lexical tags are search aids, not validated semantic labels.

The corpus contains 374 nonempty messages: 183 in full visibility and 191 in partial visibility, across seeds 20–23. Messages sent in round t are available in round t+1. Final-round messages have no measured subsequent recipient action.

In partial visibility, explicit dollar amounts in 124 messages match actual round-t quotes omitted from at least one recipient's next-round historical display: 302 recipient/quote candidate rows. Of these, 221 rows from 106 messages match the sender's own actual quote. These are not 106 confirmed factual relays: a matching value can be a proposal or coincidence. Several recipients can share one message. Full visibility has zero masked-quote matches by construction, not as an estimated behavioural effect.

## Coding rules

Keep separate, nonexclusive codes for factual price reports, price-reduction recommendations, price-increase recommendations, coordination requests, liquidity rationales, unsupported beliefs, and discrepancies between concrete own-action claims and actual submitted orders. Separately assess direct-display availability and global novelty. A hidden quote may remain inferable from previous messages, memory or realized transactions. Recommendations are not factual reports, and intentions are not completed actions. Leave ambiguous judgments UNKNOWN.

## Reviewed evidence

1. Seed 20, partial ON, round 1, Jin: “Adjusted my ask to $84.00…” His submitted ask was $84. That quote is omitted from Kit and Nia's round-2 historical displays. This is an accurate self-price report conveying recipient-masked information. Kit next asks $83; Nia submits no ask. Neither result establishes causal uptake or global novelty.

2. Seed 20, partial ON, round 1, Leo reports an opening ask of $82 and invites others to join. The actual ask is $82, omitted from Jin and Nia's next-round historical displays. This combines an accurate self-report with a strategic invitation.

3. Seed 20, partial ON, round 3, Jin recommends adjusting asks to $83. The amount matches his own order and a masked quote, but the statement is a recommendation, not an explicit self-report. This illustrates why numeric matches cannot all count as factual transfers.

4. Seed 20, partial ON, round 5, Jin proposes coordinating asks to $82.50 or below while submitting $83. This is a proposal/action discrepancy, not a false claim that he already asked $82.50.

5. Seed 22, partial ON, round 3, Yara says “My new ask is $81.50…” but the market records no submitted ask for her that round. The narration disagrees with the recorded action. Raw output and standing-order context should be checked before assigning a stronger factual-error category.

6. Seed 23, partial ON, round 2, Mia says she will lower her ask to $84 but submits no ask. This is an intention/action mismatch, distinct from a false completed-action report.

## Interpretation

Accurate self-price reports carrying directly masked quote information exist in this corpus. We have not established their prevalence as genuinely novel information, their causal influence, or mediation of the trade-volume interaction. Lexical lower-price flags occur in 94 full and 75 partial messages; coordination flags occur in 58 and 79. These are transparent search counts only. No lexical flag establishes motive, competence, deception or cartel membership.

Files: messages.csv retains every message and UNREVIEWED semantic fields; recipient_hidden_price_candidates.csv retains recipient-specific matches; summary.json gives mechanical counts. Original evidence bundles are unchanged.
