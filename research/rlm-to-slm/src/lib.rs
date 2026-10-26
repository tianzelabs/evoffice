//! Stable, language-neutral records for distilling RLM/REPL behaviour into an
//! analytics SLM. The model consumes WorkspaceState and emits an Action; the
//! executor remains the authority for data and numeric results.

use serde::{Deserialize, Serialize};

pub type ObjectId = String;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkspaceState {
    pub run_id: String,
    pub task_id: String,
    pub market_window: DataWindow,
    pub objects: Vec<WorkspaceObject>,
    pub recent_actions: Vec<ActionRecord>,
    pub remaining_budget: Budget,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataWindow {
    pub start_ms: i64,
    pub end_ms: i64,
    pub rows: u64,
    pub source: String,
    pub held_out: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkspaceObject {
    pub id: ObjectId,
    pub kind: ObjectKind,
    pub fields: Vec<FieldSpec>,
    pub provenance: Vec<ObjectId>,
    pub freshness_ms: i64,
    pub reusable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ObjectKind {
    RawTable,
    Profile,
    DerivedTable,
    WindowMetric,
    Comparison,
    Hypothesis,
    Validation,
    Result,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FieldSpec {
    pub name: String,
    pub data_type: String,
    pub nullable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Budget {
    pub remaining_queries: u32,
    pub remaining_compute_ms: u64,
    pub max_recursion_depth: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActionRecord {
    pub action: Action,
    pub observation: Option<Observation>,
    pub valid: bool,
    pub latency_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Action {
    InspectSchema {
        source: ObjectId,
    },
    Profile {
        source: ObjectId,
    },
    Filter {
        source: ObjectId,
        predicate: Predicate,
    },
    Aggregate {
        source: ObjectId,
        group_by: Vec<String>,
        metrics: Vec<Metric>,
    },
    WindowMetric {
        source: ObjectId,
        field: String,
        window: u32,
        metric: String,
    },
    Compare {
        left: ObjectId,
        right: ObjectId,
        metric: String,
    },
    Validate {
        object: ObjectId,
        against: DataWindow,
    },
    CreateHypothesis {
        target: String,
        relation: Relation,
    },
    Reuse {
        object: ObjectId,
    },
    Invalidate {
        object: ObjectId,
        reason: String,
    },
    Fallback {
        reason: String,
    },
    Finish {
        result: ObjectId,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Predicate {
    pub field: String,
    pub operator: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Metric {
    pub field: String,
    pub function: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Relation {
    pub direction: String,
    pub confidence: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Observation {
    pub created_objects: Vec<ObjectId>,
    pub numeric_checks: Vec<NumericCheck>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NumericCheck {
    pub name: String,
    pub value: f64,
    pub reference_value: Option<f64>,
    pub absolute_error: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrajectoryStep {
    pub step: u32,
    pub state: WorkspaceState,
    pub teacher_action: Action,
    pub result: Observation,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trajectory {
    pub schema_version: u32,
    pub run_id: String,
    pub model: String,
    pub steps: Vec<TrajectoryStep>,
}
