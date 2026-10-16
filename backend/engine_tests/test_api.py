import io


def create_project(client, headers):
    response = client.post("/api/v1/projects", headers=headers, json={
        "name":"API Test Project","customer":"Demo Customer","country":"Indonesia",
        "cities":["Jakarta"],"categories":["Hair Salon"],"target_volume":10,
        "confidence_threshold":70,"gold_threshold":85
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_project_create_and_dashboard(client, headers):
    project = create_project(client, headers)
    response = client.get(f"/api/v1/dashboard/{project['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["A_total"] == 0
    assert response.json()["invariant_a_equals_b_plus_c_plus_i"] is True


def test_csv_import_preserves_pending_status(client, headers):
    project = create_project(client, headers)
    csv_data = b"business_name,category,full_address,city,province,latitude,longitude,phone,primary_source_url\nSalon API,Hair Salon,Jl Test,Jakarta,DKI Jakarta,-6.2,106.8,+62123,https://example.com\n"
    response = client.post("/api/v1/imports/poi", headers=headers, data={"project_id":project["id"],"source_name":"Test Upload"}, files={"file":("test.csv",io.BytesIO(csv_data),"text/csv")})
    assert response.status_code == 200, response.text
    assert response.json()["imported"] == 1
    rows = client.get(f"/api/v1/candidates?project_id={project['id']}", headers=headers).json()["items"]
    assert rows[0]["google_status"] == "GOOGLE_CHECK_PENDING"
    assert rows[0]["usability_eligible"] is False


def test_absent_review_requires_query_and_evidence(client, headers):
    project = create_project(client, headers)
    csv_data = b"business_name,category\nSalon API,Hair Salon\n"
    imported = client.post("/api/v1/imports/poi", headers=headers, data={"project_id":project["id"],"source_name":"Test"}, files={"file":("test.csv",io.BytesIO(csv_data),"text/csv")}).json()
    candidate_id = imported["candidate_ids"][0]
    response = client.post(f"/api/v1/candidates/{candidate_id}/google-review", headers=headers, json={
        "decision":"GOOGLE_ABSENT_VERIFIED","completed":True,"reason":"Reviewed all checks","queries":[],"candidate_place_ids":[]
    })
    assert response.status_code == 422


def test_export_returns_xlsx(client, headers):
    project = create_project(client, headers)
    response = client.get(f"/api/v1/exports/{project['id']}/xlsx", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
