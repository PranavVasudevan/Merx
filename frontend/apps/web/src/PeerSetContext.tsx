import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from './api';

// D5 (docs/audit/04-remediation-prompts.md): a named, persisted, arbitrary
// list of certs a user builds once (from search, a screener result, a
// cluster, or an M&A candidate list) and can then filter population-scoped
// pages/charts/percentiles down to. `activePeerSet` is `null` by default
// (unchanged behavior — every consumer sees the full population).
export interface PeerSet {
  id: number;
  name: string;
  certs: number[];
  created_at: string;
}

interface PeerSetContextValue {
  peerSets: PeerSet[];
  activePeerSet: PeerSet | null;
  setActivePeerSetId: (id: number | null) => void;
  createPeerSet: (name: string, certs: number[]) => Promise<void>;
  deletePeerSet: (id: number) => Promise<void>;
  reload: () => void;
}

const PeerSetContext = createContext<PeerSetContextValue | null>(null);

export function PeerSetProvider({ children }: { children: ReactNode }) {
  const [peerSets, setPeerSets] = useState<PeerSet[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);

  const reload = useCallback(() => {
    api.getPeerSets().then((r) => setPeerSets(r.items)).catch(() => setPeerSets([]));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  async function createPeerSet(name: string, certs: number[]) {
    const r = await api.savePeerSet(name, certs);
    setPeerSets(r.items);
  }

  async function deletePeerSet(id: number) {
    const r = await api.deletePeerSet(id);
    setPeerSets(r.items);
    if (activeId === id) setActiveId(null);
  }

  const activePeerSet = peerSets.find((p) => p.id === activeId) ?? null;

  return (
    <PeerSetContext.Provider value={{
      peerSets, activePeerSet, setActivePeerSetId: setActiveId, createPeerSet, deletePeerSet, reload,
    }}>
      {children}
    </PeerSetContext.Provider>
  );
}

export function usePeerSet(): PeerSetContextValue {
  const ctx = useContext(PeerSetContext);
  if (!ctx) throw new Error('usePeerSet must be used within a PeerSetProvider');
  return ctx;
}
