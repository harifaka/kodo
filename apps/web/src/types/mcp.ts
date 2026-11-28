/** Phase 15 MCP server status surfaced by `GET /api/v1/mcp/info`. */
export interface McpToolInfo {
  name: string;
  description: string;
  readOnly: boolean;
}

export interface McpInfo {
  enabled: boolean;
  endpointPath: string;
  protocol: string;
  toolCount: number;
  tools: McpToolInfo[];
  transports: string[];
  protocolVersions: string[];
  mode: string;
  saasRequiresAuth: boolean;
  rateLimitPerMinute: number;
}
