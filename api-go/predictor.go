package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"

	ort "github.com/yalue/onnxruntime_go"
)

// Predictor 는 거리(km)와 대기 주문 수로 예상 시간(분)을 돌려준다.
type Predictor func(distanceKm, pendingOrders float64) (float64, error)

// newOnnxPredictor 는 ONNX 모델(입력 "X" [1, 2] float32 → 출력 "variable")을 읽어 예측기를 만든다.
// 정규화는 모델 안에 있어 따로 하지 않는다. 세션과 텐서를 요청 사이에 같이 쓰므로 잠금으로 한 번에 하나만 실행한다.
func newOnnxPredictor(libPath, modelPath string) (Predictor, func(), error) {
	ort.SetSharedLibraryPath(libPath)
	if err := ort.InitializeEnvironment(); err != nil {
		return nil, nil, fmt.Errorf("ONNX Runtime 시작 실패(%s): %w", libPath, err)
	}
	in, err := ort.NewEmptyTensor[float32](ort.NewShape(1, 2))
	if err != nil {
		return nil, nil, err
	}
	out, err := ort.NewEmptyTensor[float32](ort.NewShape(1, 1))
	if err != nil {
		return nil, nil, err
	}
	session, err := ort.NewAdvancedSession(modelPath, []string{"X"}, []string{"variable"},
		[]ort.Value{in}, []ort.Value{out}, nil)
	if err != nil {
		return nil, nil, fmt.Errorf("모델 읽기 실패(%s): %w", modelPath, err)
	}
	var mu sync.Mutex
	predict := func(km, orders float64) (float64, error) {
		mu.Lock()
		defer mu.Unlock()
		data := in.GetData()
		data[0], data[1] = float32(km), float32(orders)
		if err := session.Run(); err != nil {
			return 0, err
		}
		return float64(out.GetData()[0]), nil
	}
	closeAll := func() {
		session.Destroy()
		in.Destroy()
		out.Destroy()
		_ = ort.DestroyEnvironment()
	}
	return predict, closeAll, nil
}

func modelPath() string {
	dir := os.Getenv("MODEL_DIR")
	if dir == "" {
		dir = "artifacts"
	}
	return filepath.Join(dir, "model_sklearn.onnx")
}
