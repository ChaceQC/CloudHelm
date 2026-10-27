//! Bounded unresolved commands per Hub/user; original bodies and keys stay fixed.

use crate::bridge::HubRequest;
use rusqlite::{params, Connection, OptionalExtension};
use tauri::{AppHandle, Manager};

fn database(app: &AppHandle) -> Result<Connection, String> {
    let directory = app.path().app_data_dir().map_err(|_| "command_journal_unavailable")?;
    std::fs::create_dir_all(&directory).map_err(|_| "command_journal_unavailable")?;
    let db = Connection::open(directory.join("commands.sqlite3")).map_err(|_| "command_journal_unavailable")?;
    db.execute_batch("PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS pending_commands (
            account TEXT NOT NULL, key TEXT NOT NULL, request TEXT NOT NULL, PRIMARY KEY(account,key));")
        .map_err(|_| "command_journal_unavailable")?;
    Ok(db)
}

pub fn load(app: &AppHandle, account: &str) -> Result<Vec<HubRequest>, String> {
    let db = database(app)?;
    let mut statement = db.prepare("SELECT request FROM pending_commands WHERE account=?1 ORDER BY rowid LIMIT 101")
        .map_err(|_| "command_journal_unavailable")?;
    let rows = statement.query_map([account], |row| row.get::<_, String>(0))
        .map_err(|_| "command_journal_unavailable")?;
    let mut result = Vec::new();
    for row in rows {
        let value = row.map_err(|_| "command_journal_unavailable")?;
        result.push(serde_json::from_str(&value).map_err(|_| "command_journal_invalid")?);
    }
    if result.len() > 100 { return Err("command_journal_full".into()); }
    Ok(result)
}

pub fn prepare(app: &AppHandle, account: &str, request: &HubRequest) -> Result<(), String> {
    let mut db = database(app)?;
    let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|_| "command_journal_unavailable")?;
    let value = serde_json::to_string(request).map_err(|_| "command_invalid")?;
    let key = request.idempotency_key.as_deref().ok_or("idempotency_key_required")?;
    let previous: Option<String> = tx.query_row("SELECT request FROM pending_commands WHERE account=?1 AND key=?2", params![account,key],
        |row| row.get(0)).optional().map_err(|_| "command_journal_unavailable")?;
    if previous.as_ref().is_some_and(|p| p != &value) { return Err("original_command_unresolved".into()); }
    let count: i64 = tx.query_row("SELECT count(*) FROM pending_commands WHERE account=?1", [account], |row| row.get(0))
        .map_err(|_| "command_journal_unavailable")?;
    if previous.is_none() && count >= 100 { return Err("command_journal_full".into()); }
    tx.execute("INSERT OR IGNORE INTO pending_commands(account,key,request) VALUES (?1,?2,?3)", params![account, key, value])
        .map_err(|_| "command_journal_unavailable")?;
    tx.commit().map_err(|_| "command_journal_unavailable".into())
}

pub fn settle(app: &AppHandle, account: &str, key: &str) -> Result<(), String> {
    let db = database(app)?;
    db.execute("DELETE FROM pending_commands WHERE account=?1 AND key=?2",
        params![account, key]).map_err(|_| "command_journal_unavailable")?;
    Ok(())
}
