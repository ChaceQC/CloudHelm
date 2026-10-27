//! Bounded unresolved commands per Hub/user; original bodies and keys stay fixed.

use crate::bridge::{HubRequest, Reply};
use rusqlite::{params, Connection, OptionalExtension};
use tauri::{AppHandle, Manager};

fn database(app: &AppHandle) -> Result<Connection, String> {
    let directory = app.path().app_data_dir().map_err(|_| "command_journal_unavailable")?;
    std::fs::create_dir_all(&directory).map_err(|_| "command_journal_unavailable")?;
    let db = Connection::open(directory.join("commands.sqlite3")).map_err(|_| "command_journal_unavailable")?;
    db.execute_batch("PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS pending_commands (
            account TEXT NOT NULL, key TEXT NOT NULL, request TEXT NOT NULL, PRIMARY KEY(account,key));
        CREATE TABLE IF NOT EXISTS command_receipts (
            account TEXT NOT NULL, key TEXT NOT NULL, reply TEXT NOT NULL, PRIMARY KEY(account,key));")
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
    if previous.is_some() { return Err("original_command_unresolved".into()); }
    let count: i64 = tx.query_row("SELECT count(*) FROM pending_commands WHERE account=?1", [account], |row| row.get(0))
        .map_err(|_| "command_journal_unavailable")?;
    if count >= 100 { return Err("command_journal_full".into()); }
    tx.execute("INSERT OR IGNORE INTO pending_commands(account,key,request) VALUES (?1,?2,?3)", params![account, key, value])
        .map_err(|_| "command_journal_unavailable")?;
    tx.commit().map_err(|_| "command_journal_unavailable".into())
}

pub fn get(app: &AppHandle, account: &str, key: &str) -> Result<(HubRequest, Option<Reply>), String> {
    let db = database(app)?;
    let (request, receipt): (String, Option<String>) = db.query_row(
        "SELECT p.request, r.reply FROM pending_commands p LEFT JOIN command_receipts r
         ON p.account=r.account AND p.key=r.key WHERE p.account=?1 AND p.key=?2",
        params![account, key], |row| Ok((row.get(0)?, row.get(1)?)))
        .optional().map_err(|_| "command_journal_unavailable")?.ok_or("original_command_unavailable")?;
    let request = serde_json::from_str(&request).map_err(|_| "command_journal_invalid")?;
    let receipt = receipt.map(|value| serde_json::from_str(&value).map_err(|_| "command_journal_invalid"))
        .transpose()?;
    Ok((request, receipt))
}

pub fn record(app: &AppHandle, account: &str, key: &str, reply: &Reply) -> Result<Reply, String> {
    let mut db = database(app)?;
    let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|_| "command_journal_unavailable")?;
    let value = serde_json::to_string(reply).map_err(|_| "command_journal_invalid")?;
    let count = tx.execute("INSERT OR IGNORE INTO command_receipts(account,key,reply)
        SELECT account,key,?3 FROM pending_commands WHERE account=?1 AND key=?2",
        params![account, key, value]).map_err(|_| "command_journal_unavailable")?;
    let stored: Option<String> = tx.query_row("SELECT reply FROM command_receipts WHERE account=?1 AND key=?2",
        params![account, key], |row| row.get(0)).optional().map_err(|_| "command_journal_unavailable")?;
    if count == 0 && stored.is_none() { return Err("original_command_unavailable".into()); }
    let stored: Reply = serde_json::from_str(&stored.ok_or("command_journal_invalid")?)
        .map_err(|_| "command_journal_invalid")?;
    if crate::bridge::command_id(&stored) != crate::bridge::command_id(reply) {
        return Err("original_receipt_conflict".into());
    }
    tx.commit().map_err(|_| "command_journal_unavailable")?;
    Ok(stored)
}

pub fn settle(app: &AppHandle, account: &str, key: &str) -> Result<(), String> {
    let mut db = database(app)?;
    let tx = db.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
        .map_err(|_| "command_journal_unavailable")?;
    let pending: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM pending_commands WHERE account=?1 AND key=?2)",
        params![account, key], |row| row.get(0)).map_err(|_| "command_journal_unavailable")?;
    let receipt: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM command_receipts WHERE account=?1 AND key=?2)",
        params![account, key], |row| row.get(0)).map_err(|_| "command_journal_unavailable")?;
    if pending && !receipt { return Err("command_unconfirmed".into()); }
    tx.execute("DELETE FROM pending_commands WHERE account=?1 AND key=?2", params![account, key])
        .map_err(|_| "command_journal_unavailable")?;
    tx.execute("DELETE FROM command_receipts WHERE account=?1 AND key=?2", params![account, key])
        .map_err(|_| "command_journal_unavailable")?;
    tx.commit().map_err(|_| "command_journal_unavailable".into())
}
