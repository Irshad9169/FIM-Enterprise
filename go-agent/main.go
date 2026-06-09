package main

import (
    "bytes"
    "crypto/sha256"
    "encoding/json"
    "flag"
    "fmt"
    "io"
    "log"
    "net/http"
    "os"
    "path/filepath"
    "runtime"
    "strings"
    "syscall"
    "time"
)

type ServerConfig struct {
    URL    string
    APIKey string
}

type MonitoringConfig struct {
    Paths           []string
    ScanInterval    int
    ExcludePatterns []string
}

type Config struct {
    Server     ServerConfig
    AgentID    string
    Monitoring MonitoringConfig
}

type FileInfo struct {
    Path         string `json:"path"`
    Size         int64  `json:"size"`
    Permissions  string `json:"permissions"`
    Owner        int    `json:"owner"`
    Group        int    `json:"group"`
    ModifiedTime string `json:"modified_time"`
    Hash         string `json:"hash"`
}

type RegisterRequest struct {
    Hostname     string `json:"hostname"`
    IPAddress    string `json:"ip_address,omitempty"`
    OSType       string `json:"os_type"`
    OSVersion    string `json:"os_version"`
    AgentVersion string `json:"agent_version"`
}

type RegisterResponse struct {
    Success bool   `json:"success"`
    AgentID string `json:"agent_id"`
    Message string `json:"message"`
}

type ScanSubmitRequest struct {
    AgentID    string                   `json:"agent_id"`
    Timestamp  string                   `json:"timestamp"`
    Files      []map[string]interface{} `json:"files"`
    TotalFiles int                      `json:"total_files"`
}

type FIMAgent struct {
    config   Config
    hostname string
    agentID  string
    client   *http.Client
}

func loadConfig(path string) (*Config, error) {
    config := &Config{
        Server: ServerConfig{
            URL: "http://test06.hyd.int.untd.com:8000",
        },
        Monitoring: MonitoringConfig{
            Paths:        []string{"/etc", "/usr/sbin"},
            ScanInterval: 21600,
            ExcludePatterns: []string{".swp", ".tmp", "/proc", "/sys", "/dev", "cache"},
        },
    }
    return config, nil
}

func saveAgentID(configPath, agentID string) error {
    data := fmt.Sprintf("agent_id: %s\n", agentID)
    return os.WriteFile(configPath, []byte(data), 0644)
}

func calculateHash(filePath string) (string, error) {
    file, err := os.Open(filePath)
    if err != nil {
        return "", err
    }
    defer file.Close()

    hash := sha256.New()
    if _, err := io.Copy(hash, file); err != nil {
        return "", err
    }

    return fmt.Sprintf("%x", hash.Sum(nil)), nil
}

func shouldExclude(path string, patterns []string) bool {
    for _, pattern := range patterns {
        if strings.Contains(path, pattern) {
            return true
        }
    }
    return false
}

func getFileOwnership(info os.FileInfo) (int, int) {
    stat, ok := info.Sys().(*syscall.Stat_t)
    if !ok {
        return 0, 0
    }
    return int(stat.Uid), int(stat.Gid)
}

func (a *FIMAgent) scanFiles() ([]FileInfo, error) {
    var results []FileInfo
    log.Printf("Starting scan of %d paths", len(a.config.Monitoring.Paths))

    for _, basePath := range a.config.Monitoring.Paths {
        filepath.Walk(basePath, func(path string, info os.FileInfo, err error) error {
            if err != nil {
                return nil
            }

            if shouldExclude(path, a.config.Monitoring.ExcludePatterns) {
                if info.IsDir() {
                    return filepath.SkipDir
                }
                return nil
            }

            if !info.IsDir() {
                hash, err := calculateHash(path)
                if err != nil {
                    return nil
                }

                owner, group := getFileOwnership(info)

                fileInfo := FileInfo{
                    Path:         path,
                    Size:         info.Size(),
                    Permissions:  fmt.Sprintf("%04o", info.Mode().Perm()),
                    Owner:        owner,
                    Group:        group,
                    ModifiedTime: info.ModTime().Format(time.RFC3339),
                    Hash:         hash,
                }
                results = append(results, fileInfo)
            }
            return nil
        })
    }

    log.Printf("Scan complete: %d files scanned", len(results))
    return results, nil
}

func (a *FIMAgent) register() (string, error) {
    hostname, _ := os.Hostname()

    req := RegisterRequest{
        Hostname:     hostname,
        OSType:       runtime.GOOS,
        OSVersion:    runtime.GOARCH,
        AgentVersion: "1.0.0-go",
    }

    jsonData, err := json.Marshal(req)
    if err != nil {
        return "", err
    }

    resp, err := a.client.Post(
        a.config.Server.URL+"/api/v1/agents/",
        "application/json",
        bytes.NewBuffer(jsonData),
    )
    if err != nil {
        return "", err
    }
    defer resp.Body.Close()

    var result RegisterResponse
    if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
        return "", err
    }

    log.Printf("Agent registered: %s", result.AgentID)
    return result.AgentID, nil
}

func (a *FIMAgent) submitScan(files []FileInfo) error {
    filesMaps := make([]map[string]interface{}, len(files))
    for i, f := range files {
        filesMaps[i] = map[string]interface{}{
            "path":          f.Path,
            "size":          f.Size,
            "permissions":   f.Permissions,
            "owner":         f.Owner,
            "group":         f.Group,
            "modified_time": f.ModifiedTime,
            "hash":          f.Hash,
        }
    }

    req := ScanSubmitRequest{
        AgentID:    a.agentID,
        Timestamp:  time.Now().UTC().Format(time.RFC3339),
        Files:      filesMaps,
        TotalFiles: len(files),
    }

    jsonData, err := json.Marshal(req)
    if err != nil {
        return err
    }

    resp, err := a.client.Post(
        a.config.Server.URL+"/api/v1/scans/submit",
        "application/json",
        bytes.NewBuffer(jsonData),
    )
    if err != nil {
        return err
    }
    defer resp.Body.Close()

    if resp.StatusCode != 200 {
        return fmt.Errorf("scan submission failed: %d", resp.StatusCode)
    }

    log.Printf("Scan results sent: %d files", len(files))
    return nil
}

func (a *FIMAgent) runScan() error {
    log.Println("============================================================")
    log.Println("Starting file integrity scan")

    files, err := a.scanFiles()
    if err != nil {
        return err
    }

    if len(files) > 0 {
        if err := a.submitScan(files); err != nil {
            return err
        }
    }

    log.Println("Scan complete")
    log.Println("============================================================")
    return nil
}

func (a *FIMAgent) runDaemon() {
    log.Printf("FIM Agent started (PID: %d)", os.Getpid())
    log.Printf("Server: %s", a.config.Server.URL)
    log.Printf("Scan interval: %d seconds", a.config.Monitoring.ScanInterval)

    for {
        if err := a.runScan(); err != nil {
            log.Printf("Scan error: %v", err)
        }
        log.Printf("Sleeping for %d seconds...", a.config.Monitoring.ScanInterval)
        time.Sleep(time.Duration(a.config.Monitoring.ScanInterval) * time.Second)
    }
}

func main() {
    configPath := flag.String("config", "config/agent_config.yaml", "Config file path")
    registerFlag := flag.Bool("register", false, "Register agent and exit")
    scanOnce := flag.Bool("scan-once", false, "Run one scan and exit")
    flag.Parse()

    config, _ := loadConfig(*configPath)

    agent := &FIMAgent{
        config: *config,
        agentID: config.AgentID,
        client: &http.Client{Timeout: 30 * time.Second},
    }

    if *registerFlag {
        agentID, err := agent.register()
        if err != nil {
            log.Fatalf("Registration failed: %v", err)
        }
        agent.agentID = agentID
        saveAgentID(*configPath, agentID)
        return
    }

    if agent.agentID == "" {
        agentID, err := agent.register()
        if err != nil {
            log.Fatalf("Registration failed: %v", err)
        }
        agent.agentID = agentID
    }

    if *scanOnce {
        if err := agent.runScan(); err != nil {
            log.Fatalf("Scan failed: %v", err)
        }
    } else {
        agent.runDaemon()
    }
}
