from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response

from app.schemas.analysis import AnalysisResult, ProductionAnalysisRequest
from app.schemas.evaluation_job import EvaluationJobResponse
from app.schemas.signal import SignalEvaluationResponse
from app.services.evaluation_jobs import EvaluationJobs

def no_store(response: Response) -> None:
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(prefix='/evaluations', tags=['evaluations'], dependencies=[Depends(no_store)])


def get_evaluation_jobs(request: Request) -> EvaluationJobs:
    return request.app.state.evaluation_jobs


@router.post('', status_code=202, response_model=EvaluationJobResponse)
async def create_evaluation(request: ProductionAnalysisRequest,
    research_token: str | None = Header(default=None, alias='X-Research-Cutoff-Token'),
    jobs: EvaluationJobs = Depends(get_evaluation_jobs)) -> EvaluationJobResponse:
    return jobs.create(request, research_token)


@router.get('/{evaluation_id}', response_model=EvaluationJobResponse)
async def evaluation_status(evaluation_id: UUID,
    research_token: str | None = Header(default=None, alias='X-Research-Cutoff-Token'),
    jobs: EvaluationJobs = Depends(get_evaluation_jobs)) -> EvaluationJobResponse:
    return jobs.status(evaluation_id, research_token)


@router.delete('/{evaluation_id}', response_model=EvaluationJobResponse)
async def cancel_evaluation(evaluation_id: UUID,
    research_token: str | None = Header(default=None, alias='X-Research-Cutoff-Token'),
    jobs: EvaluationJobs = Depends(get_evaluation_jobs)) -> EvaluationJobResponse:
    return await jobs.cancel(evaluation_id, research_token)


@router.get('/{evaluation_id}/signal', response_model=SignalEvaluationResponse)
async def evaluation_signal(evaluation_id: UUID,
    research_token: str | None = Header(default=None, alias='X-Research-Cutoff-Token'),
    jobs: EvaluationJobs = Depends(get_evaluation_jobs)) -> Response:
    return Response(jobs.result(evaluation_id, 'signal', research_token), media_type='application/json', headers={'Cache-Control': 'no-store'})


@router.get('/{evaluation_id}/analysis', response_model=AnalysisResult)
async def evaluation_analysis(evaluation_id: UUID,
    research_token: str | None = Header(default=None, alias='X-Research-Cutoff-Token'),
    jobs: EvaluationJobs = Depends(get_evaluation_jobs)) -> Response:
    return Response(jobs.result(evaluation_id, 'analysis', research_token), media_type='application/json', headers={'Cache-Control': 'no-store'})
