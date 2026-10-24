"""Deterministic quote omission, without changing the auction's true state."""
import hashlib
import random
from pathlib import Path
from typing import Literal

from .auction import ResearchMarket
from .io import append

DISCLOSURE = ('\nObservation policy: displayed quote lists may omit rival seller quotes. '
              'An omitted quote is unobserved, not evidence of a withdrawal. '
              'Your own information and realized trades remain available.')


def mask_visible(seed, observer, owner, quote_round):
    """One stable observer/quote draw; independent of price, messages and list order."""
    if observer == owner:
        return True
    key = f'information-mask-v1|{seed}|{observer}|{owner}|{quote_round}'
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big') >= 2**63


class ObservationMarket(ResearchMarket):
    visibility_mode: Literal['full', 'partial', 'shuffled'] = 'full'
    observation_path: Path | None = None
    observation_seed: int = 0

    def visible(self, observer, owner, quote_round):
        return self.visibility_mode != 'partial' or mask_visible(
            self.observation_seed, observer, owner, quote_round)

    def observation_for(self, agent, common):
        view = super().observation_for(agent, common)
        seller = agent.id.startswith('Seller ')
        masks = []
        if seller:
            rendered = []
            for price, owner in common['ask_queue']:
                origin = next((r.round_number for r in reversed(self.rounds)
                               if owner in r.seller_asks), 0)
                visible = self.visible(agent.id, owner, origin)
                masks.append(dict(owner=owner, quote_round=origin, price=price, visible=visible))
                if visible:
                    rendered.append((price, owner))
            view['ask_queue'] = rendered
            history = []
            historical_masks = []
            for row in self.rounds[-5:]:
                history.append(f'Hour {row.round_number}:')
                for owner in sorted(row.seller_asks):
                    visible = self.visible(agent.id, owner, row.round_number)
                    historical_masks.append(dict(owner=owner, quote_round=row.round_number,
                                                 price=row.seller_asks[owner], visible=visible))
                    if visible:
                        history.append(f'  {owner} ask ${row.seller_asks[owner]}')
                for owner in sorted(row.buyer_bids):
                    history.append(f'  {owner} bid ${row.buyer_bids[owner]}')
            view['past_bids_and_asks'] = ('\n'.join(history) if history else 'No bids or asks yet.') + DISCLOSURE
            if self.visibility_mode == 'shuffled':
                key = f'quote-order-v1|{self.observation_seed}|{agent.id}|{common["round_num"]}'
                random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big')).shuffle(view['ask_queue'])
        else:
            historical_masks = []
        if self.observation_path is not None:
            append(self.observation_path, dict(
                seed=self.observation_seed, round=common['round_num'], observer=agent.id,
                role='seller' if seller else 'buyer', mode=self.visibility_mode,
                true_observation=common, rendered_observation=view,
                current_quote_masks=masks, historical_quote_masks=historical_masks))
        return view
