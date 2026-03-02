# --- The Financial Analyst Brain (v2.2: Strategic Summarizer) ---

import json
import os
from enum import Enum
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --- Constants ---
ENTITY_ARCHIVE_FILE = 'entity_archive.json'

# --- Analyst Vocabulary ---
class DecisionType(str, Enum):
    BUY_OPPORTUNITY = "BUY_OPPORTUNITY"
    WATCH = "WATCH"
    HIGH_RISK = "HIGH_RISK"
    NEUTRAL = "NEUTRAL"
    GO_IDLE = "GO_IDLE"
    EJECT = "EJECT"
    FOCUS = "FOCUS"

@dataclass
class AnalysisDecision:
    entity_id: str
    behavior: str
    narrative: str
    decision_type: DecisionType
    confidence: float
    pair_name: str
    metrics: dict = field(default_factory=dict)

# --- Archival Helper Functions ---

def load_entity_archive():
    """Loads the persistent entity data from the JSON file."""
    if not os.path.exists(ENTITY_ARCHIVE_FILE):
        return {}
    try:
        with open(ENTITY_ARCHIVE_FILE, 'r') as f:
            content = f.read()
            if not content: return {}
            # Correctly reload from the file handle
            f.seek(0)
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_entity_archive(data):
    """Atomically writes the entity data to the JSON file to prevent race conditions."""
    temp_file_path = ENTITY_ARCHIVE_FILE + ".tmp"
    final_file_path = ENTITY_ARCHIVE_FILE
    
    try:
        with open(temp_file_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.rename(temp_file_path, final_file_path)
    except (IOError, OSError) as e:
        print(f"ANALYST: Error during atomic write of entity archive: {e}")
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError as cleanup_e:
                print(f"ANALYST: Error cleaning up temp file: {cleanup_e}")

# --- The Brain Itself ---

class FinancialAnalyst:
    def __init__(self, pair_name: str):
        self.pair_name = pair_name
        self._eject_warning_counts = defaultdict(int)
        self.no_activity_cycles = 0
        self.MAX_NO_ACTIVITY_CYCLES_BEFORE_IDLE = 5

    def run_full_analysis(self, transactions: list) -> list[AnalysisDecision]:
        if not transactions:
            self.no_activity_cycles += 1
            if self.no_activity_cycles >= self.MAX_NO_ACTIVITY_CYCLES_BEFORE_IDLE:
                self.no_activity_cycles = 0
                return [AnalysisDecision(
                    entity_id="SYSTEM", behavior="PROLONGED_INACTIVITY",
                    narrative=f"No new swaps detected for {self.MAX_NO_ACTIVITY_CYCLES_BEFORE_IDLE} cycles.",
                    decision_type=DecisionType.GO_IDLE, confidence=0.9, pair_name=self.pair_name)]
            return []

        self.no_activity_cycles = 0
        temp_entities = self._identify_entities(transactions)
        if not temp_entities: return []

        metrics = self._calculate_behavioral_metrics(transactions, temp_entities)
        decisions = self._generate_strategic_decisions(metrics, temp_entities)
        return decisions

    def _find_cycles(self, graph):
        path, visited, cycles = [], set(), []
        def dfs(node):
            path.append(node)
            visited.add(node)
            for neighbor in graph.get(node, []):
                if neighbor in path:
                    try:
                        cycle_start_index = path.index(neighbor)
                        cycles.append(path[cycle_start_index:])
                    except ValueError: pass
                    continue
                if neighbor not in visited: dfs(neighbor)
            path.pop()
        for node in list(graph.keys()):
            if node not in visited: dfs(node)
        unique_cycles = []
        seen_cycles = set()
        for c in cycles:
            canonical = tuple(sorted(c))
            if canonical not in seen_cycles:
                unique_cycles.append(c)
                seen_cycles.add(canonical)
        return unique_cycles

    def _identify_entities(self, transactions: list) -> dict:
        graph = defaultdict(set)
        for tx in transactions:
            for transfer in tx.get("tokenTransfers", []):
                f, t = transfer.get("fromUserAccount"), transfer.get("toUserAccount")
                if f and t and f != t: graph[f].add(t)
        cycles = self._find_cycles(graph)
        return {f"TempEntity-{i+1}": wallets for i, wallets in enumerate(cycles)}

    def _calculate_behavioral_metrics(self, transactions: list, entities: dict) -> dict:
        metrics = defaultdict(lambda: {"internal_volume_usd": 0, "absorbed_volume_usd": 0, "sold_volume_usd": 0, "absorption_rate": 0, "sell_to_buy_ratio": 0, "total_tx": 0})
        wallet_to_entity = {w: eid for eid, ws in entities.items() for w in ws}
        total_external_sell_vol = 0
        for tx in transactions:
            if tx.get("type") != "SWAP": continue
            usd_val = tx.get("financial_analysis", {}).get("usd_value")
            if not usd_val: continue
            
            involved_entities = set()
            for tf in tx.get("tokenTransfers", []):
                from_w, to_w = tf.get("fromUserAccount"), tf.get("toUserAccount")
                from_e, to_e = wallet_to_entity.get(from_w), wallet_to_entity.get(to_w)
                
                if from_e: involved_entities.add(from_e)
                if to_e: involved_entities.add(to_e)

                if from_e and from_e == to_e:
                    metrics[from_e]["internal_volume_usd"] += usd_val
                    break
                if to_e and not from_e:
                    metrics[to_e]["absorbed_volume_usd"] += usd_val
                if from_e and not to_e:
                    metrics[from_e]["sold_volume_usd"] += usd_val

            for eid in involved_entities:
                metrics[eid]["total_tx"] += 1

            if not any(wallet_to_entity.get(p) for p in [tx.get("feePayer")]):
                 total_external_sell_vol += usd_val
                 
        for eid, data in metrics.items():
            if total_external_sell_vol > 0:
                data["absorption_rate"] = (data["absorbed_volume_usd"] / total_external_sell_vol) * 100
            if data["absorbed_volume_usd"] > 0:
                data["sell_to_buy_ratio"] = data["sold_volume_usd"] / data["absorbed_volume_usd"]
        return dict(metrics)

    def _generate_strategic_decisions(self, metrics: dict, temp_entities: dict) -> list[AnalysisDecision]:
        decisions = []
        if not metrics: return []

        archive = load_entity_archive()
        wallet_map = {wallet: entity_id for entity_id, data in archive.items() for wallet in data.get('wallets', [])}
        archive_updated = False

        for temp_id, data in metrics.items():
            behavior, narrative, decision_type, confidence = "NEUTRAL", "Behavior inconclusive.", DecisionType.NEUTRAL, 0.5
            
            absorb_rate = data.get('absorption_rate', 0)
            sell_ratio = data.get('sell_to_buy_ratio', 0)
            internal_vol = data.get('internal_volume_usd', 0)

            if internal_vol > 20000 and absorb_rate > 60:
                behavior, narrative, decision_type, confidence = "HEAVY_ACCUMULATION", f"Actively absorbing {absorb_rate:.1f}% of external sells.", DecisionType.BUY_OPPORTUNITY, 0.95
            elif absorb_rate > 40:
                behavior, narrative, decision_type, confidence = "ABSORBING_LIQUIDITY", f"Absorbing {absorb_rate:.1f}% of sell pressure.", DecisionType.BUY_OPPORTUNITY, 0.80
            elif internal_vol > 5000:
                 behavior, narrative, decision_type, confidence = "SIGNIFICANT_INTERNAL_ACTIVITY", f"High internal volume (${internal_vol:,.0f}).", DecisionType.WATCH, 0.70
            elif absorb_rate < 10 and sell_ratio > 5 and internal_vol < 1000:
                behavior, narrative, decision_type, confidence = "DUMPING_SUSPECTED", f"Suspected dumping activity.", DecisionType.HIGH_RISK, 0.8
            
            if decision_type != DecisionType.NEUTRAL:
                wallets = temp_entities[temp_id]
                persistent_id = next((wallet_map[w] for w in wallets if w in wallet_map), None)
                
                if persistent_id is None:
                    persistent_id = f"Entity-{int(datetime.now(timezone.utc).timestamp())}"
                    archive[persistent_id] = {
                        'wallets': wallets,
                        'first_seen_utc': datetime.now(timezone.utc).isoformat(),
                        'seen_on_pairs': [self.pair_name],
                        'strategic_summary': {} # Initialize summary
                    }
                    narrative = f"[NEW] {narrative}"
                    archive_updated = True
                else:
                    if self.pair_name not in archive[persistent_id]['seen_on_pairs']:
                        archive[persistent_id]['seen_on_pairs'].append(self.pair_name)
                        archive_updated = True
                    narrative = f"[KNOWN] {narrative}"

                # --- HARMONY FIX: Generate and update the strategic summary ---
                strategic_decision = "BEHAVIOR_DETECTED"
                if behavior == "HEAVY_ACCUMULATION":
                    strategic_decision = "INFLECTION_POINT_DETECTED"
                elif behavior == "ABSORBING_LIQUIDITY":
                    strategic_decision = "ACCUMULATION_SUSPECTED"

                # Calculate isolation from total transactions vs internal volume
                total_transactions = data.get('total_tx', 1)
                internal_tx_ratio = data.get('internal_volume_usd', 0) / (data.get('absorbed_volume_usd', 0) + data.get('sold_volume_usd', 0) + data.get('internal_volume_usd', 1))

                summary = {
                    "decision": strategic_decision,
                    "narrative": f"Entity exhibits {behavior.replace('_', ' ').lower()} patterns. Current absorption rate is {absorb_rate:.1f}%.",
                    "friction_coefficient": data.get('internal_volume_usd', 0),
                    "isolation_score": internal_tx_ratio
                }
                
                # Update the archive with the new summary
                archive[persistent_id]['strategic_summary'] = summary
                archive_updated = True
                # --- END OF FIX ---

                decisions.append(AnalysisDecision(
                    entity_id=persistent_id, behavior=behavior, narrative=narrative, decision_type=decision_type,
                    confidence=confidence, pair_name=self.pair_name, metrics=data))

                if behavior == "HEAVY_ACCUMULATION":
                    decisions.append(AnalysisDecision(
                        entity_id=persistent_id, behavior="FOCUS_ENGAGED", narrative="High market activity detected, focusing observation.",
                        decision_type=DecisionType.FOCUS, confidence=0.9, pair_name=self.pair_name, metrics={}))

        if archive_updated:
            save_entity_archive(archive)
        
        return decisions
