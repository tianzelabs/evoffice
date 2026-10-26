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

impl Trajectory {
    /// Check the invariants required before a trajectory can enter a training
    /// set. This validates the record, not the underlying market calculation;
    /// the executor/evaluator remains responsible for that.
    pub fn validate(&self) -> Result<(), Vec<String>> {
        let mut errors = Vec::new();

        if self.schema_version == 0 {
            errors.push("schema_version must be positive".to_owned());
        }
        if self.run_id.is_empty() {
            errors.push("run_id must not be empty".to_owned());
        }
        if self.steps.is_empty() {
            errors.push("trajectory must contain at least one step".to_owned());
        }

        for (expected_step, step) in self.steps.iter().enumerate() {
            if step.step != expected_step as u32 {
                errors.push(format!(
                    "step {} is numbered {}, expected {}",
                    expected_step, step.step, expected_step
                ));
            }
            if step.state.run_id != self.run_id {
                errors.push(format!("step {} has a different run_id", step.step));
            }
            for check in &step.result.numeric_checks {
                if !check.value.is_finite() {
                    errors.push(format!("step {} has a non-finite numeric value", step.step));
                }
                if let Some(reference) = check.reference_value {
                    if !reference.is_finite() {
                        errors.push(format!(
                            "step {} has a non-finite reference value",
                            step.step
                        ));
                    }
                }
                if let Some(error) = check.absolute_error {
                    if error.is_sign_negative() || !error.is_finite() {
                        errors.push(format!("step {} has an invalid absolute error", step.step));
                    }
                }
            }
        }

        if errors.is_empty() {
            Ok(())
        } else {
            Err(errors)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Trajectory {
        Trajectory {
            schema_version: 1,
            run_id: "run-001".to_owned(),
            model: "teacher-rlm".to_owned(),
            steps: vec![TrajectoryStep {
                step: 0,
                state: WorkspaceState {
                    run_id: "run-001".to_owned(),
                    task_id: "rolling-volatility".to_owned(),
                    market_window: DataWindow {
                        start_ms: 1,
                        end_ms: 2,
                        rows: 2,
                        source: "paper-btc-1m".to_owned(),
                        held_out: false,
                    },
                    objects: vec![],
                    recent_actions: vec![],
                    remaining_budget: Budget {
                        remaining_queries: 10,
                        remaining_compute_ms: 1_000,
                        max_recursion_depth: 4,
                    },
                },
                teacher_action: Action::Profile {
                    source: "bars".to_owned(),
                },
                result: Observation {
                    created_objects: vec!["bars-profile".to_owned()],
                    numeric_checks: vec![NumericCheck {
                        name: "row_count".to_owned(),
                        value: 2.0,
                        reference_value: Some(2.0),
                        absolute_error: Some(0.0),
                    }],
                    error: None,
                },
            }],
        }
    }

    #[test]
    fn trajectory_round_trips_as_structured_json() {
        let original = sample();
        let encoded = serde_json::to_string(&original).expect("serialize trajectory");
        let decoded: Trajectory = serde_json::from_str(&encoded).expect("deserialize trajectory");
        assert_eq!(decoded.run_id, original.run_id);
        assert!(decoded.validate().is_ok());
        assert!(encoded.contains("\"op\":\"profile\""));
    }

    #[test]
    fn invalid_step_order_is_rejected() {
        let mut trajectory = sample();
        trajectory.steps[0].step = 3;
        let errors = trajectory.validate().expect_err("invalid step must fail");
        assert!(errors.iter().any(|error| error.contains("expected 0")));
    }

    #[test]
    fn invalid_numeric_values_are_rejected() {
        let mut trajectory = sample();
        trajectory.steps[0].result.numeric_checks[0].value = f64::NAN;
        assert!(trajectory.validate().is_err());
    }
}
