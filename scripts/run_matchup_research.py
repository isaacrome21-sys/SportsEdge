#!/usr/bin/env python3
"""Execute explicit JSON research inputs; never fetch, fit, stake or promote.

Usage: python scripts/run_matchup_research.py {nrfi,td,price,board} input.json
Outputs JSON to stdout. See docs/research/matchup_role_adoption_20260921.md.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(mode, data):
    data = dict(data)
    if mode == 'board':
        from sportsedge.research.scored_board import build_scored_board
        from datetime import timezone
        data.setdefault('now', datetime.now(timezone.utc))
        return build_scored_board(**data)
    if mode == 'nrfi':
        from sportsedge.research.first_inning_matchup import (
            BatterOBP, FirstInningParameters, PitcherFirstInning, predict_first_inning,
        )
        for field in ('features_as_of', 'prediction_at', 'first_pitch'):
            data[field] = datetime.fromisoformat(data[field])
        params = dict(data['parameters'])
        params['training_end'] = datetime.fromisoformat(params['training_end'])
        data['parameters'] = FirstInningParameters(**params)
        for field in ('away_pitcher', 'home_pitcher'):
            data[field] = PitcherFirstInning(**data[field])
        for field in ('away_top3', 'home_top3'):
            data[field] = [BatterOBP(**row) for row in data[field]]
        return predict_first_inning(**data)
    if mode == 'price':
        from sportsedge.research.market_value import compare_price
        for field in ('quote_at', 'now', 'start'):
            if data.get(field) is not None:
                data[field] = datetime.fromisoformat(data[field])
        return compare_price(**data)
    if mode == 'td':
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.usage import PlayerUsageProfile, TeamUsageProfile
        from sportsedge.research.preplay_td_roles import (
            PreplayRoleAllocator, ZoneRole, summarize_offensive_touchdowns,
        )
        def usage(raw):
            return TeamUsageProfile(team=raw['team'], quarterback_id=raw['quarterback_id'],
                                    players=tuple(PlayerUsageProfile(**p) for p in raw['players']))
        allocator = PreplayRoleAllocator(usage(data['home_usage']), usage(data['away_usage']),
            roles={key: ZoneRole(**value) for key, value in data['roles'].items()}, seed=data['seed'])
        paths = [FootballPlayPath(**{**raw, 'plays': tuple(PlayEvent(**p) for p in raw['plays'])})
                 for raw in data['paths']]
        result = summarize_offensive_touchdowns(allocator.attribute_many(paths),
                                               player_ids=data['player_ids'])
        from sportsedge.source_lineage import canonical_json_sha256
        result['input_sha256'] = canonical_json_sha256({'version': allocator.version, 'input': data})
        return result
    raise ValueError('UNSUPPORTED_RESEARCH_MODE')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('nrfi', 'td', 'price', 'board'))
    parser.add_argument('input', type=Path)
    parser.add_argument('--format', choices=('json', 'markdown'), default='json')
    parser.add_argument('--limit', type=int, default=5, help='Maximum positive-EV candidates in the board')
    parser.add_argument('--min-score', type=float, default=60, help='Display cutoff, not calibrated confidence')
    parser.add_argument('--all-lines', action='store_true', help='Show the full board audit, including unscored lines')
    args = parser.parse_args()
    if args.format == 'markdown' and args.mode != 'board':
        parser.error('--format markdown requires board mode')
    result = run(args.mode, json.loads(args.input.read_text()))
    if args.format == 'markdown':
        from sportsedge.research.scored_board import render_scored_board
        print(render_scored_board(result, limit=args.limit, min_score=args.min_score,
                                  show_all=args.all_lines), end='')
    else:
        print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
