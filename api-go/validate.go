package main

import (
	"bytes"
	"encoding/json"
	"math"
	"regexp"
	"strconv"
)

// 설계서 2.1 의 입력 검증. pydantic(strict=True) 과 같은 판정을 JSON 글자 그대로 본다.

const maxDistanceKm = 20.0

// fieldError 는 FastAPI 기본 422 본문의 detail 항목과 같은 모양이다.
type fieldError struct {
	Type  string `json:"type"`
	Loc   []any  `json:"loc"`
	Msg   string `json:"msg"`
	Input any    `json:"input"`
}

type etaInput struct {
	DistanceKm    float64
	PendingOrders float64 // 정수 글자만 받는다. 모델 입력이 실수라 실수로 들고 있다
}

var integerToken = regexp.MustCompile(`^-?(0|[1-9][0-9]*)$`)

func bodyError(typ, msg string, loc []any, input any) []fieldError {
	return []fieldError{{Type: typ, Loc: loc, Msg: msg, Input: input}}
}

// parseEtaRequest 는 본문을 검사해 입력을 돌려주거나, 422 로 돌려줄 오류 목록을 돌려준다.
func parseEtaRequest(body []byte) (etaInput, []fieldError) {
	if !json.Valid(body) {
		// NaN, Infinity 글자도 JSON 문법 오류라 여기서 거절한다
		return etaInput{}, bodyError("json_invalid", "JSON decode error", []any{"body", 0}, map[string]any{})
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(body, &fields); err != nil || fields == nil {
		var any_ any
		_ = json.Unmarshal(body, &any_)
		return etaInput{}, bodyError("model_attributes_type",
			"Input should be a valid dictionary or object to extract fields from", []any{"body"}, any_)
	}
	whole := rawToAny(body)

	var errs []fieldError
	var in etaInput

	if raw, ok := fields["distance_km"]; !ok {
		errs = append(errs, fieldError{"missing", []any{"body", "distance_km"}, "Field required", whole})
	} else if v, e := checkDistance(raw); e != nil {
		errs = append(errs, *e)
	} else {
		in.DistanceKm = v
	}

	if raw, ok := fields["pending_orders"]; !ok {
		errs = append(errs, fieldError{"missing", []any{"body", "pending_orders"}, "Field required", whole})
	} else if v, e := checkOrders(raw); e != nil {
		errs = append(errs, *e)
	} else {
		in.PendingOrders = v
	}

	if len(errs) > 0 {
		return etaInput{}, errs
	}
	return in, nil
}

func checkDistance(raw json.RawMessage) (float64, *fieldError) {
	loc := []any{"body", "distance_km"}
	tok := string(bytes.TrimSpace(raw))
	if !isNumberToken(tok) { // 따옴표 친 숫자, true/false, null, 객체 등
		return 0, &fieldError{"float_type", loc, "Input should be a valid number", rawToAny(raw)}
	}
	v, err := strconv.ParseFloat(tok, 64)
	if err != nil || math.IsInf(v, 0) || math.IsNaN(v) { // 1e309 처럼 무한대가 되는 값
		return 0, &fieldError{"finite_number", loc, "Input should be a finite number", jsonSafe(v)}
	}
	if v < 0 {
		return 0, &fieldError{"greater_than_equal", loc, "Input should be greater than or equal to 0", v}
	}
	if v > maxDistanceKm {
		return 0, &fieldError{"less_than_equal", loc, "Input should be less than or equal to 20", v}
	}
	return v, nil
}

func checkOrders(raw json.RawMessage) (float64, *fieldError) {
	loc := []any{"body", "pending_orders"}
	tok := string(bytes.TrimSpace(raw))
	if !integerToken.MatchString(tok) { // 소수점·지수가 있는 값(2.0 포함), 문자열, true/false, null
		return 0, &fieldError{"int_type", loc, "Input should be a valid integer", rawToAny(raw)}
	}
	v, _ := strconv.ParseFloat(tok, 64)
	if v < 0 {
		return 0, &fieldError{"greater_than_equal", loc, "Input should be greater than or equal to 0", rawToAny(raw)}
	}
	return v, nil
}

func isNumberToken(tok string) bool {
	if tok == "" {
		return false
	}
	c := tok[0]
	return c == '-' || (c >= '0' && c <= '9')
}

// rawToAny 는 오류 본문의 input 에 넣을 값을 만든다.
func rawToAny(raw []byte) any {
	var v any
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if err := d.Decode(&v); err != nil {
		return string(raw)
	}
	return v
}

// jsonSafe 는 JSON 으로 쓸 수 없는 무한대·NaN 을 문자열로 바꾼다(설계서 2.1 마지막 항목).
func jsonSafe(v float64) any {
	switch {
	case math.IsNaN(v):
		return "nan"
	case math.IsInf(v, 1):
		return "inf"
	case math.IsInf(v, -1):
		return "-inf"
	}
	return v
}
