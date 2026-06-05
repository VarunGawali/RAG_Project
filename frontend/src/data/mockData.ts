import type { Contract, ChatSession, Message, Citation } from '../types'

// ─── Contracts ────────────────────────────────────────────────────────────────

export const MOCK_CONTRACTS: Contract[] = [
  {
    id: 'Edison_NYPA_OandM_Contract_1',
    displayName: 'Edison NYPA O&M Contract',
    fileName: 'Edison_NYPA_OandM_Contract_1.pdf',
    status: 'graph_ready',
    uploadedAt: '2024-11-01',
    pageCount: 142,
    fileSize: '4.2 MB',
    graphReady: true,
    clauseCount: 160,
    entityCount: 313,
  },
  {
    id: 'SoCal_Gas_Service_Agreement',
    displayName: 'SoCal Gas Service Agreement',
    fileName: 'SoCal_Gas_Service_Agreement.pdf',
    status: 'search_only',
    uploadedAt: '2024-11-08',
    pageCount: 88,
    fileSize: '2.8 MB',
    graphReady: false,
    clauseCount: 97,
  },
  {
    id: 'NextEra_PPA_2024',
    displayName: 'NextEra Power Purchase Agreement',
    fileName: 'NextEra_PPA_2024.pdf',
    status: 'search_only',
    uploadedAt: '2024-11-12',
    pageCount: 115,
    fileSize: '3.6 MB',
    graphReady: false,
    clauseCount: 128,
  },
  {
    id: 'Terra_Wind_EPC_Contract',
    displayName: 'Terra Wind EPC Contract',
    fileName: 'Terra_Wind_EPC_Contract.pdf',
    status: 'search_only',
    uploadedAt: '2024-11-15',
    pageCount: 203,
    fileSize: '6.1 MB',
    graphReady: false,
    clauseCount: 211,
  },
  {
    id: 'NYISO_Interconnection_Agreement',
    displayName: 'NYISO Interconnection Agreement',
    fileName: 'NYISO_Interconnection_Agreement.pdf',
    status: 'search_only',
    uploadedAt: '2024-11-18',
    pageCount: 67,
    fileSize: '1.9 MB',
    graphReady: false,
    clauseCount: 74,
  },
]

// ─── Citations ────────────────────────────────────────────────────────────────

const cit1: Citation = {
  id: 'c1',
  contractId: 'Edison_NYPA_OandM_Contract_1',
  contractName: 'Edison NYPA O&M Contract',
  clauseTitle: '12.4 Community Right to Know',
  sectionTitle: 'ARTICLE XII — Environmental Compliance',
  pageRange: '34–35',
  sourcePath: 'Edison NYPA O&M > ARTICLE XII > 12.4',
  evidenceQuote:
    'Con Edison shall develop and maintain a chemical inventory subject to reporting requirements and notify Power Authority within five (5) business days of any new or removed chemicals.',
  route: 'hybrid',
  score: 0.94,
}

const cit2: Citation = {
  id: 'c2',
  contractId: 'Edison_NYPA_OandM_Contract_1',
  contractName: 'Edison NYPA O&M Contract',
  clauseTitle: '12.1 Environmental Laws',
  sectionTitle: 'ARTICLE XII — Environmental Compliance',
  pageRange: '32–33',
  sourcePath: 'Edison NYPA O&M > ARTICLE XII > 12.1',
  evidenceQuote:
    'Power Authority shall conduct operations in compliance with all applicable Environmental Laws and shall promptly notify Con Edison of any known or reasonably anticipated violation.',
  route: 'hybrid',
  score: 0.91,
}

const cit3: Citation = {
  id: 'c3',
  contractId: 'Edison_NYPA_OandM_Contract_1',
  contractName: 'Edison NYPA O&M Contract',
  clauseTitle: '15.2 Termination for Cause',
  sectionTitle: 'ARTICLE XV — Termination',
  pageRange: '58–60',
  sourcePath: 'Edison NYPA O&M > ARTICLE XV > 15.2',
  evidenceQuote:
    'In the event of a material breach that remains uncured for thirty (30) days following written notice, the non-Breaching Party may terminate this Agreement by providing sixty (60) days written notice.',
  route: 'search',
  score: 0.88,
}

const cit4: Citation = {
  id: 'c4',
  contractId: 'Edison_NYPA_OandM_Contract_1',
  contractName: 'Edison NYPA O&M Contract',
  clauseTitle: '8.3 Indemnification by Con Edison',
  sectionTitle: 'ARTICLE VIII — Indemnification',
  pageRange: '28–29',
  sourcePath: 'Edison NYPA O&M > ARTICLE VIII > 8.3',
  evidenceQuote:
    'Con Edison shall indemnify, defend, and hold harmless Power Authority from and against any and all Claims arising out of or relating to Con Edison\'s gross negligence or willful misconduct.',
  route: 'graph',
  score: 0.96,
}

// ─── Messages ─────────────────────────────────────────────────────────────────

const graphMessages: Message[] = [
  {
    id: 'm1',
    role: 'user',
    content: 'What obligations does Con Edison have under this contract?',
    timestamp: '2024-11-20T10:15:00Z',
  },
  {
    id: 'm2',
    role: 'assistant',
    content: `Based on the Edison NYPA O&M Contract, **Con Edison holds 74 obligations** across 20 clauses. Key obligation categories:

**Reporting & Notification**
- Notify Power Authority within **5 business days** of chemical inventory changes (§12.4)
- Submit Material Safety Data Sheets within **3 months** of O&M Commencement Date (§12.4)
- Provide copies of all regulatory filings to Power Authority (§12.6)

**Environmental Compliance**
- Develop and maintain chemical inventory subject to EPA/OSHA reporting (§12.4)
- Implement Risk Management Plan (RMP) following Power Authority review and approval (§12.5)
- Appoint Emergency Coordinator and notify SERC and LEPC within **60 days** of EHS presence (§12.4)

**Operational Obligations**
- Conduct periodic inspections to monitor compliance with the RMP (§12.5)
- Maintain all O&M records and make them available for audit upon reasonable notice (§9.2)
- Carry and maintain specified insurance coverage throughout the term (§11.1)

**Financial Obligations**
- Indemnify Power Authority against claims arising from Con Edison's gross negligence or willful misconduct (§8.3)
- Pay all fees and charges associated with regulatory filings (§12.4)`,
    timestamp: '2024-11-20T10:15:04Z',
    route: 'graph',
    citations: [cit4, cit1],
    contractsQueried: ['Edison_NYPA_OandM_Contract_1'],
    entityCount: 74,
    executionMs: 1240,
    followUpSuggestions: [
      'Which of these obligations have strict deadlines?',
      'What are Power Authority\'s obligations in return?',
      'What happens if Con Edison fails to meet these obligations?',
    ],
  },
]

const hybridMessages: Message[] = [
  {
    id: 'm3',
    role: 'user',
    content: 'What environmental reporting obligations exist under the agreement?',
    timestamp: '2024-11-20T11:00:00Z',
  },
  {
    id: 'm4',
    role: 'assistant',
    content: `The agreement imposes **several layered environmental reporting obligations** under Article XII.

**Primary Obligations (Power Authority)**
- Prepare, submit, and maintain the **Risk Management Plan (RMP)** and provide Con Edison a draft at least 30 days prior to O&M Commencement Date
- Conduct periodic facility inspections to monitor RMP compliance
- File **Facility Inventory Forms (209-U)** and other hazardous substance disclosure forms after O&M Commencement Date

**Primary Obligations (Con Edison)**
- Develop and maintain a **chemical inventory** subject to SARA Title III / EPCRA reporting
- Notify Power Authority within 5 business days of any newly introduced or removed EHS chemicals
- Obtain and submit **Material Safety Data Sheets** for all EHS and OSHA hazardous substances within 3 months

**Regulatory Notifications**
- Appoint an **Emergency Coordinator** and notify the State Emergency Response Commission (SERC) and Local Emergency Planning Committee (LEPC) within 60 days of EHS presence

Both parties must promptly notify the other of any known or reasonably anticipated violation of applicable Environmental Laws (§12.1).`,
    timestamp: '2024-11-20T11:00:06Z',
    route: 'hybrid',
    citations: [cit1, cit2],
    contractsQueried: ['Edison_NYPA_OandM_Contract_1'],
    entityCount: 12,
    executionMs: 1870,
    followUpSuggestions: [
      'Which party is responsible for the Risk Management Plan?',
      'What are the notice periods for environmental violations?',
      'What are the consequences of failing to file these reports?',
    ],
  },
]

const searchMessages: Message[] = [
  {
    id: 'm5',
    role: 'user',
    content: 'Summarize Article XII.',
    timestamp: '2024-11-20T14:00:00Z',
  },
  {
    id: 'm6',
    role: 'assistant',
    content: `**Article XII — Environmental Compliance** spans pages 32–40 and governs the environmental responsibilities of both parties throughout the O&M period.

**Scope**
The article establishes a comprehensive framework for compliance with federal, state, and local environmental laws, including SARA Title III, EPCRA, OSHA HazCom, and the Clean Air Act Risk Management Program rules.

**Key Provisions**
- **§12.1 Environmental Laws** — Both parties must operate in compliance with all applicable Environmental Laws and promptly notify each other of known or anticipated violations.
- **§12.2 Hazardous Materials** — Power Authority is responsible for the safe handling, storage, and disposal of all hazardous materials at the facility.
- **§12.3 SF6 Gas Management** — Specific obligations around SF6 leak detection, reporting thresholds, and remediation timelines given the facility's high-voltage equipment.
- **§12.4 Community Right to Know** — Detailed reporting obligations under SARA Title III including chemical inventories, MSDS sheets, emergency coordinator appointments, and LEPC notifications.
- **§12.5 Risk Management Plan** — Power Authority must maintain an RMP; Con Edison must review and approve implementation provisions.
- **§12.6 Regulatory Filings** — All regulatory filings must be shared with the other party; filing fees are allocated to the responsible party.

**Risk Allocation**
Liability for pre-existing environmental conditions is explicitly carved out and remains with Con Edison; new conditions arising during the O&M period are allocated based on the party whose operations caused them.`,
    timestamp: '2024-11-20T14:00:05Z',
    route: 'search',
    citations: [cit1, cit2],
    contractsQueried: ['Edison_NYPA_OandM_Contract_1'],
    executionMs: 980,
    followUpSuggestions: [
      'What specific reporting deadlines does Article XII impose?',
      'How does Article XII allocate liability for pre-existing contamination?',
      'What rights does Con Edison have to approve the Risk Management Plan?',
    ],
  },
]

const crossContractMessages: Message[] = [
  {
    id: 'm7',
    role: 'user',
    content: 'What are the termination notice periods across all contracts?',
    timestamp: '2024-11-20T15:30:00Z',
  },
  {
    id: 'm8',
    role: 'assistant',
    content: `Across **5 contracts** in your portfolio, termination notice periods vary significantly by contract type:

| Contract | Termination for Cause | Termination for Convenience | Cure Period |
|----------|----------------------|----------------------------|-------------|
| Edison NYPA O&M | 60 days written notice | 180 days | 30 days |
| SoCal Gas Service Agreement | 45 days written notice | 120 days | 15 days |
| NextEra PPA 2024 | 30 days written notice | 365 days | 30 days |
| Terra Wind EPC | 45 days written notice | Not permitted | 20 days |
| NYISO Interconnection | 90 days written notice | 180 days | 30 days |

**Key Observations**
- **Longest cure period**: Edison NYPA O&M (30 days) — consistent with the complexity and scale of O&M obligations
- **Shortest termination for cause**: NextEra PPA 2024 (30 days) — typical for power purchase agreements where market exposure is time-sensitive
- **No convenience termination**: Terra Wind EPC — standard for fixed-price construction contracts to protect against project abandonment
- **Longest convenience notice**: NextEra PPA 2024 (365 days) — protects long-term renewable generation commitments

> ⚠️ **Note:** Deep clause analysis is available for Edison NYPA only. Results for other contracts are based on document text and may be less precise.`,
    timestamp: '2024-11-20T15:30:08Z',
    route: 'search',
    citations: [cit3],
    contractsQueried: [
      'Edison_NYPA_OandM_Contract_1',
      'SoCal_Gas_Service_Agreement',
      'NextEra_PPA_2024',
      'Terra_Wind_EPC_Contract',
      'NYISO_Interconnection_Agreement',
    ],
    executionMs: 2340,
    followUpSuggestions: [
      'Which contracts allow termination for convenience?',
      'What constitutes a material breach across these contracts?',
      'Show me the exact termination clause in the Edison NYPA contract.',
    ],
  },
]

// ─── Sessions ─────────────────────────────────────────────────────────────────

export const MOCK_SESSIONS: ChatSession[] = [
  {
    id: 's1',
    title: 'Edison — Obligations Analysis',
    createdAt: '2024-11-20T10:14:00Z',
    updatedAt: '2024-11-20T10:15:04Z',
    messages: graphMessages,
    contractFilter: 'Edison_NYPA_OandM_Contract_1',
    previewText: 'Con Edison holds 74 obligations across 20 clauses...',
  },
  {
    id: 's2',
    title: 'Environmental Compliance Review',
    createdAt: '2024-11-20T10:59:00Z',
    updatedAt: '2024-11-20T11:00:06Z',
    messages: hybridMessages,
    contractFilter: 'Edison_NYPA_OandM_Contract_1',
    previewText: '12 environment-related obligations identified...',
  },
  {
    id: 's3',
    title: 'Article XII Deep-Dive',
    createdAt: '2024-11-20T13:59:00Z',
    updatedAt: '2024-11-20T14:00:05Z',
    messages: searchMessages,
    contractFilter: 'Edison_NYPA_OandM_Contract_1',
    previewText: 'Article XII governs environmental responsibilities...',
  },
  {
    id: 's4',
    title: 'Cross-Contract Termination Review',
    createdAt: '2024-11-20T15:29:00Z',
    updatedAt: '2024-11-20T15:30:08Z',
    messages: crossContractMessages,
    contractFilter: null,
    previewText: 'Termination notice periods vary across 5 contracts...',
  },
]

// ─── Mock AI response generator ───────────────────────────────────────────────

export function getMockResponse(question: string, contractFilter: string | null): Message {
  const q = question.toLowerCase()
  const id = `msg_${Date.now()}`

  if (q.includes('obligation') && (q.includes('con edison') || q.includes('edison'))) {
    return { ...graphMessages[1], id, timestamp: new Date().toISOString() }
  }
  if (q.includes('environmental') || q.includes('reporting')) {
    return { ...hybridMessages[1], id, timestamp: new Date().toISOString() }
  }
  if (q.includes('article xii') || q.includes('article 12')) {
    return { ...searchMessages[1], id, timestamp: new Date().toISOString() }
  }
  if (q.includes('termination') && !contractFilter) {
    return { ...crossContractMessages[1], id, timestamp: new Date().toISOString() }
  }
  if (q.includes('deadline') || q.includes('due')) {
    return {
      id,
      role: 'assistant',
      content: `The contract identifies **3 obligations with explicit deadlines**:\n\n1. **Chemical Inventory** — Must be developed prior to O&M Commencement Date (§12.4)\n2. **Material Safety Data Sheets** — Must be obtained and submitted within **3 months** of O&M Commencement Date (§12.4)\n3. **Emergency Coordinator Notification** — SERC and LEPC must be notified within **60 days** of EHS presence at the facility (§12.4)\n\nAdditionally, several obligations carry **notice period requirements**:\n- Chemical changes → 5 business days notice to Power Authority\n- Draft RMP delivery → at least 30 days prior to O&M Commencement Date`,
      timestamp: new Date().toISOString(),
      route: 'graph',
      citations: [cit1],
      contractsQueried: ['Edison_NYPA_OandM_Contract_1'],
      entityCount: 3,
      executionMs: 1050,
      followUpSuggestions: [
        'What are the consequences of missing these deadlines?',
        'Are there any cure periods if a deadline is breached?',
        'Which party bears responsibility for the Environmental Coordinator appointment?',
      ],
    }
  }

  return {
    id,
    role: 'assistant',
    content: `I searched your contract portfolio for: **"${question}"**\n\nI found relevant clauses across ${contractFilter ? '1 contract' : 'your contracts'}. For more specific results, try asking about particular parties, obligations, deadlines, or specific articles.\n\n**Try asking:**\n- What obligations does Con Edison have?\n- Which obligations have deadlines?\n- Summarize Article XII.\n- What are the termination provisions?`,
    timestamp: new Date().toISOString(),
    route: 'search',
    citations: [],
    contractsQueried: contractFilter ? [contractFilter] : MOCK_CONTRACTS.map(c => c.id),
    executionMs: 820,
    followUpSuggestions: [
      'What are the key obligations in this contract?',
      'What are the termination provisions?',
      'Which party carries the most risk?',
    ],
  }
}