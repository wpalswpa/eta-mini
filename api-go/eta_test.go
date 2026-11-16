package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// 기대값은 설계서 2절의 규칙에서 정했다. 예측기는 가짜라 ONNX Runtime 이 없어도 돈다.

type call struct{ km, orders float64 }

func newTestServer(calls *[]call) *server {
	return &server{model: "test", predict: func(km, orders float64) (float64, error) {
		if calls != nil {
			*calls = append(*calls, call{km, orders})
		}
		return 23.5, nil
	}}
}

func post(t *testing.T, s *server, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/eta", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	s.handler().ServeHTTP(rec, req)
	return rec
}

func locs(t *testing.T, rec *httptest.ResponseRecorder) [][]any {
	t.Helper()
	var out struct {
		Detail []struct {
			Loc []any `json:"loc"`
		} `json:"detail"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("422 본문이 JSON 이 아니다: %v: %s", err, rec.Body.String())
	}
	var all [][]any
	for _, d := range out.Detail {
		all = append(all, d.Loc)
	}
	return all
}

func hasLoc(all [][]any, field string) bool {
	for _, l := range all {
		if len(l) == 2 && l[0] == "body" && l[1] == field {
			return true
		}
	}
	return false
}

func TestEtaReturnsMinutesAndModel(t *testing.T) {
	// 정상 입력: 200, 본문은 minutes 와 model 두 필드뿐이다
	rec := post(t, newTestServer(nil), `{"distance_km": 3, "pending_orders": 2}`)
	if rec.Code != 200 {
		t.Fatalf("상태 %d: %s", rec.Code, rec.Body.String())
	}
	var got map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &got)
	if len(got) != 2 || got["minutes"] != 23.5 || got["model"] != "test" {
		t.Fatalf("본문이 다르다: %v", got)
	}
}

func TestEtaPassesDistanceThenOrders(t *testing.T) {
	// 인자 순서는 거리, 대기 주문 수다(바뀌면 모델에 거꾸로 들어간다)
	var calls []call
	post(t, newTestServer(&calls), `{"distance_km": 2.5, "pending_orders": 7}`)
	if len(calls) != 1 || calls[0] != (call{2.5, 7}) {
		t.Fatalf("예측기 호출이 다르다: %v", calls)
	}
}

func TestEtaAcceptsBoundaries(t *testing.T) {
	// 경계값: 0, 상한 20, 큰 주문 수, 모르는 필드는 모두 200
	for _, body := range []string{
		`{"distance_km": 0, "pending_orders": 0}`,
		`{"distance_km": 20, "pending_orders": 0}`,
		`{"distance_km": 20.0, "pending_orders": 1000}`,
		`{"distance_km": 3, "pending_orders": 2, "weather": "rain"}`,
		`{"distance_km": 3, "pending_orders": 99999999999999999999}`,
	} {
		if rec := post(t, newTestServer(nil), body); rec.Code != 200 {
			t.Errorf("%s → %d: %s", body, rec.Code, rec.Body.String())
		}
	}
}

func TestEtaRejectsInvalidInput(t *testing.T) {
	// 422 로 거절하고 loc 가 문제 필드를 가리킨다
	cases := []struct{ body, field string }{
		{`{"pending_orders": 2}`, "distance_km"},
		{`{"distance_km": 3}`, "pending_orders"},
		{`{"distance_km": -1, "pending_orders": 2}`, "distance_km"},
		{`{"distance_km": 20.5, "pending_orders": 2}`, "distance_km"},
		{`{"distance_km": 1e309, "pending_orders": 2}`, "distance_km"},
		{`{"distance_km": "3", "pending_orders": 2}`, "distance_km"},
		{`{"distance_km": true, "pending_orders": 2}`, "distance_km"},
		{`{"distance_km": null, "pending_orders": 2}`, "distance_km"},
		{`{"distance_km": "abc", "pending_orders": 2}`, "distance_km"},
		{`{"distance_km": 3, "pending_orders": -1}`, "pending_orders"},
		{`{"distance_km": 3, "pending_orders": 1.5}`, "pending_orders"},
		{`{"distance_km": 3, "pending_orders": 2.0}`, "pending_orders"},
		{`{"distance_km": 3, "pending_orders": 2e0}`, "pending_orders"},
		{`{"distance_km": 3, "pending_orders": "2"}`, "pending_orders"},
		{`{"distance_km": 3, "pending_orders": true}`, "pending_orders"},
	}
	for _, c := range cases {
		var calls []call
		rec := post(t, newTestServer(&calls), c.body)
		if rec.Code != 422 {
			t.Errorf("%s → %d (422 여야 한다)", c.body, rec.Code)
			continue
		}
		if !hasLoc(locs(t, rec), c.field) {
			t.Errorf("%s → loc 에 %s 가 없다: %s", c.body, c.field, rec.Body.String())
		}
		if len(calls) != 0 {
			t.Errorf("%s → 거절했는데 예측기를 불렀다", c.body)
		}
	}
}

func TestEtaReportsBothFieldErrors(t *testing.T) {
	// 두 필드가 모두 틀리면 오류도 두 개다
	rec := post(t, newTestServer(nil), `{}`)
	all := locs(t, rec)
	if rec.Code != 422 || !hasLoc(all, "distance_km") || !hasLoc(all, "pending_orders") {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
}

func TestEtaInfinityInputIsWrittenAsString(t *testing.T) {
	// 오류에 담긴 무한대 입력은 "inf" 문자열이다(표준 JSON 에 무한대가 없다)
	rec := post(t, newTestServer(nil), `{"distance_km": 1e309, "pending_orders": 2}`)
	if rec.Code != 422 || !strings.Contains(rec.Body.String(), `"input":"inf"`) {
		t.Fatalf("%d %s", rec.Code, rec.Body.String())
	}
}

func TestEtaRejectsMalformedBody(t *testing.T) {
	// JSON 이 아니거나 객체가 아니거나 NaN 글자가 있으면 422(500 이 아니다)
	for _, body := range []string{``, `not json`, `[1, 2]`, `3`, `"x"`, `null`, `{"distance_km": NaN, "pending_orders": 1}`, `{"distance_km": Infinity, "pending_orders": 1}`} {
		if rec := post(t, newTestServer(nil), body); rec.Code != 422 {
			t.Errorf("%q → %d: %s", body, rec.Code, rec.Body.String())
		}
	}
}

func TestEtaPredictorFailureIs500(t *testing.T) {
	// 예측기가 실패하거나 무한대를 내면 200 으로 숨기지 않고 500
	s := &server{model: "test", predict: func(_, _ float64) (float64, error) { return 0, http.ErrAbortHandler }}
	if rec := post(t, s, `{"distance_km": 1, "pending_orders": 1}`); rec.Code != 500 {
		t.Fatalf("%d", rec.Code)
	}
}

func TestHealth(t *testing.T) {
	// GET /health → 200 {"status": "ok", "model": ...}
	rec := httptest.NewRecorder()
	newTestServer(nil).handler().ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/health", nil))
	var got map[string]string
	_ = json.Unmarshal(rec.Body.Bytes(), &got)
	if rec.Code != 200 || got["status"] != "ok" || got["model"] != "test" || len(got) != 2 {
		t.Fatalf("%d %v", rec.Code, got)
	}
}

func TestUnknownPathAndWrongMethod(t *testing.T) {
	// 없는 주소 404, 다른 방법 405. 본문은 {"detail": ...}
	h := newTestServer(nil).handler()
	for _, c := range []struct {
		method, path string
		want         int
	}{{"GET", "/nope", 404}, {"GET", "/eta", 405}, {"POST", "/health", 405}} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(c.method, c.path, nil))
		if rec.Code != c.want || !strings.Contains(rec.Body.String(), `"detail"`) {
			t.Errorf("%s %s → %d %s", c.method, c.path, rec.Code, rec.Body.String())
		}
	}
}
