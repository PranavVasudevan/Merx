import type { PeerClusterResult } from '../types';
import './PeerClusterCard.css';

export function PeerClusterCard({ cluster }: { cluster: PeerClusterResult }) {
  return (
    <div className="panel">
      <h2>Feature 14 · Behavioral Peer Cluster</h2>
      <div className="pcc-label">{cluster.cluster_label}</div>
      <div className="muted pcc-size">{cluster.cluster_size} banks in this behavioral group</div>
      <div className="pcc-peers">
        <span className="muted pcc-peers-label">Sample peers:</span>
        <ul>
          {cluster.sample_peers.map((p) => <li key={p}>{p}</li>)}
        </ul>
      </div>
    </div>
  );
}
