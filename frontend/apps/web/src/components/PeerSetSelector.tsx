import { usePeerSet } from '../PeerSetContext';
import './PeerSetSelector.css';

/** D5 — global "filter population pages to this peer set" control, same
 * placement pattern as QuarterSelector. `null` (the default option) means
 * every population-scoped consumer sees the full population, unchanged. */
export function PeerSetSelector() {
  const { peerSets, activePeerSet, setActivePeerSetId } = usePeerSet();

  if (peerSets.length === 0) return null;

  return (
    <div className="peer-set-selector" title="Filter population pages to a saved peer set">
      <span className="peer-set-selector-label">Peer set</span>
      <select
        className="peer-set-selector-select"
        value={activePeerSet?.id ?? ''}
        onChange={(e) => setActivePeerSetId(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">Full population</option>
        {peerSets.map((p) => (
          <option key={p.id} value={p.id}>{p.name} ({p.certs.length})</option>
        ))}
      </select>
    </div>
  );
}
