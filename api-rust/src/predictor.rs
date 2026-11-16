//! ONNX 모델(입력 "X" [1, 2] float32 → 출력 "variable")로 예상 시간을 계산한다. 설계서 4.7.

use std::path::Path;
use std::sync::Mutex;

use ort::session::Session;
use ort::value::Tensor;

/// 거리(km)와 대기 주문 수로 예상 시간(분)을 돌려준다.
pub trait Predictor: Send + Sync {
    fn predict(&self, distance_km: f64, pending_orders: f64) -> Result<f64, String>;
}

pub struct OnnxPredictor {
    // 세션은 실행할 때 &mut 가 필요하고 요청 사이에 같이 쓰므로 잠금으로 한 번에 하나만 실행한다
    session: Mutex<Session>,
}

impl OnnxPredictor {
    /// ONNX Runtime 공유 라이브러리(lib_path)와 모델 파일을 읽는다. 정규화는 모델 안에 있어 따로 하지 않는다.
    pub fn load(lib_path: &str, model_path: &Path) -> Result<Self, String> {
        let env = ort::init_from(lib_path)
            .map_err(|e| format!("ONNX Runtime 시작 실패({lib_path}): {e}"))?
            .build()
            .map_err(|e| format!("ONNX Runtime 시작 실패({lib_path}): {e}"))?;
        let session = Session::builder(&env)
            .and_then(|mut b| b.commit_from_file(model_path))
            .map_err(|e| format!("모델 읽기 실패({}): {e}", model_path.display()))?;
        Ok(Self { session: Mutex::new(session) })
    }
}

impl Predictor for OnnxPredictor {
    fn predict(&self, distance_km: f64, pending_orders: f64) -> Result<f64, String> {
        let input = Tensor::from_array(([1usize, 2], vec![distance_km as f32, pending_orders as f32]))
            .map_err(|e| e.to_string())?;
        let mut session = self.session.lock().map_err(|e| e.to_string())?;
        let outputs = session.run(ort::inputs!["X" => input]).map_err(|e| e.to_string())?;
        let (_, data) = outputs["variable"].try_extract_tensor::<f32>().map_err(|e| e.to_string())?;
        data.first().map(|v| f64::from(*v)).ok_or_else(|| "출력이 비어 있음".to_string())
    }
}
