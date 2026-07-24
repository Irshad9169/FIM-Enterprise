export interface Scan {
  id: string;
  agent_id: string;
  scan_type: string;
  status: string;
  files_scanned: number;
  files_changed: number;
  started_at: string | null;
  completed_at: string | null;
  scan_duration?: number;
  scan_data?: {
    files: any[];
  };
}

export interface ScanListResponse {
  scans: Scan[];
  total: number;
}

export interface ScanDetail extends Scan {
  scan_data: {
    files: FileInfo[];
  };
}

export interface FileInfo {
  path: string;
  size: number;
  permissions: string;
  owner: number;
  group: number;
  modified_time: string;
  hash?: string;
}
