"""Falsify displayed rival quote values, never executable orders."""
from pathlib import Path

from ..io import append
from ..observations import DISCLOSURE, ObservationMarket, mask_visible


class DistortionMarket(ObservationMarket):
    distortion_enabled: bool = True
    distortion_log: Path | None = None

    def quote(self, observer, owner, origin, price):
        selected = self.distortion_enabled and observer != owner and not mask_visible(
            self.observation_seed, observer, owner, origin)
        shown = round(price + 10.0, 2) if selected else price
        return dict(owner=owner, quote_round=origin, true_price=price,
                    displayed_price=shown, selected=selected, offset=round(shown-price, 2))

    def observation_for(self, agent, common):
        # Parent remains full visibility. Its observation_path stays None so it
        # cannot log an intermediate truthful view as the delivered observation.
        view = super().observation_for(agent, common)
        current, historical = [], []
        if agent.id.startswith('Seller '):
            rendered = []
            for price, owner in common['ask_queue']:
                origin = next((r.round_number for r in reversed(self.rounds)
                               if owner in r.seller_asks), 0)
                record = self.quote(agent.id, owner, origin, price)
                current.append(record)
                rendered.append((record['displayed_price'], owner))
            # Preserve a plausibly sorted queue after corrupting numeric prices.
            # Changed price ranks are part of the intervention and are logged.
            view['ask_queue'] = sorted(rendered, reverse=True) if self.distortion_enabled else rendered
            history = []
            for row in self.rounds[-5:]:
                history.append(f'Hour {row.round_number}:')
                for owner in sorted(row.seller_asks):
                    record = self.quote(agent.id, owner, row.round_number, row.seller_asks[owner])
                    historical.append(record)
                    history.append(f'  {owner} ask ${record["displayed_price"]}')
                for owner in sorted(row.buyer_bids):
                    history.append(f'  {owner} bid ${row.buyer_bids[owner]}')
            view['past_bids_and_asks'] = ('\n'.join(history) if history else 'No bids or asks yet.') + DISCLOSURE
        if self.distortion_log is not None:
            append(self.distortion_log, dict(seed=self.observation_seed, round=common['round_num'],
                observer=agent.id, role='seller' if agent.id.startswith('Seller ') else 'buyer',
                mode='distort_up' if self.distortion_enabled else 'full',
                true_observation=common, rendered_observation=view,
                current_quotes=current, historical_quotes=historical))
        return view
