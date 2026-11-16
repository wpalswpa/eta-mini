// Python API(api/app.py)와 같은 계약(설계서 2.1, 2.2)을 지키는 Go 서비스. 설계서 4.6.
package main

import (
	"encoding/json"
	"io"
	"log"
	"math"
	"net/http"
	"os"
)

type server struct {
	predict Predictor
	model   string // 응답의 model 값(장애 추적용)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func (s *server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "model": s.model})
}

func (s *server) eta(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
	if err != nil {
		writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"detail": "Request Entity Too Large"})
		return
	}
	in, errs := parseEtaRequest(body)
	if errs != nil {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]any{"detail": errs})
		return
	}
	minutes, err := s.predict(in.DistanceKm, in.PendingOrders)
	if err != nil || math.IsInf(minutes, 0) || math.IsNaN(minutes) {
		log.Printf("예측 실패: %v (minutes=%v)", err, minutes)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "Internal Server Error"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"minutes": minutes, "model": s.model})
}

func (s *server) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("POST /eta", s.eta)
	// 없는 주소는 404, 있는 주소에 다른 방법이면 405(Go 기본 처리). 본문은 FastAPI 와 같은 {"detail": ...}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, pattern := mux.Handler(r)
		if pattern == "" {
			status, detail := http.StatusNotFound, "Not Found"
			if r.URL.Path == "/health" || r.URL.Path == "/eta" {
				status, detail = http.StatusMethodNotAllowed, "Method Not Allowed"
			}
			writeJSON(w, status, map[string]string{"detail": detail})
			return
		}
		mux.ServeHTTP(w, r)
	})
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	predict, closeAll, err := newOnnxPredictor(
		getenv("ONNXRUNTIME_LIB", "/opt/onnxruntime/lib/libonnxruntime.so"), modelPath())
	if err != nil {
		log.Fatal(err) // 모델이 없으면 시작하지 못한다(설계서 3절과 같은 이유)
	}
	defer closeAll()
	s := &server{predict: predict, model: getenv("MODEL_IMPL", "go-onnx")}
	addr := ":" + getenv("PORT", "8080")
	log.Printf("듣는 중 %s (model=%s)", addr, s.model)
	log.Fatal(http.ListenAndServe(addr, s.handler()))
}
