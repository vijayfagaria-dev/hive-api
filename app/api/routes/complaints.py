"""Complaint routes — file, view, accept, deny, vote, and serve proof images."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_login
from app.core.config import settings
from app.core.errors import DomainError, Forbidden, NotFound, PayloadTooLarge, UnsupportedMedia
from app.domain.enums import PHASE, ProofSource
from app.infra import storage
from app.repositories import fines as fines_repo
from app.schemas.complaints import DisputeBody, VoteBody, detail_out
from app.services import complaints

router = APIRouter(prefix="/complaints", tags=["complaints"])
proofs_router = APIRouter(prefix="/proofs", tags=["complaints"])


async def _read_proofs(images: list[UploadFile], uploaded_by: int) -> list[dict]:
    """Validate + persist uploaded images (transport concern); return proof inputs."""
    proofs: list[dict] = []
    for img in images:
        if not storage.is_allowed_image(img.content_type):
            raise UnsupportedMedia(f"“{img.filename}” isn't a supported image.")
        data = await img.read()
        if not data:
            raise DomainError("One of the images was empty.")
        if len(data) > settings.max_proof_bytes:
            mb = settings.max_proof_bytes // (1024 * 1024)
            raise PayloadTooLarge(f"Each image must be under {mb}MB.")
        ref = storage.save_upload(data, img.content_type)
        proofs.append(
            {"source": ProofSource.UPLOAD, "ref": ref, "content_type": img.content_type,
             "uploaded_by": uploaded_by}
        )
    return proofs


@router.post("")
async def create_complaint(
    accusedId: int = Form(...),
    ruleId: Optional[int] = Form(None),
    amount: Optional[int] = Form(None),
    note: Optional[str] = Form(None),
    images: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_session),
    member=Depends(require_login),
):
    if not images:
        raise DomainError("At least one photo of proof is required.")
    proofs = await _read_proofs(images, uploaded_by=member.id)
    fine_id = await complaints.create(
        session, accused_id=accusedId, added_by=member.id, rule_id=ruleId,
        amount=amount, proofs=proofs,
    )
    return {"ok": True, "complaintId": fine_id}


@router.get("/{fine_id}")
async def complaint_detail(
    fine_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    detail = await complaints.get_detail(session, fine_id, member.id)
    return detail_out(detail)


@router.post("/{fine_id}/accept")
async def accept_complaint(
    fine_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    changed = await complaints.accept(session, fine_id, member.id)
    return {"ok": True, "accepted": changed}


@router.post("/{fine_id}/dispute")
async def dispute_complaint(
    fine_id: int, body: DisputeBody,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    fine = await fines_repo.get(session, fine_id)
    if fine is None:
        raise NotFound("No such complaint.")
    if fine.added_by == member.id:
        raise Forbidden("You filed this complaint — you can't dispute it.")
    moved = await complaints.dispute(session, fine_id, by_member=member.id, reason=body.reason)
    return {"ok": True, "votingOpened": moved}


@router.post("/{fine_id}/vote")
async def vote_complaint(
    fine_id: int, body: VoteBody,
    session: AsyncSession = Depends(get_session), member=Depends(require_login),
):
    status = await complaints.cast_vote(session, fine_id, member.id, body.vote)
    tally = await fines_repo.vote_tally(session, fine_id)
    return {
        "ok": True,
        "status": status,
        "phase": PHASE.get(status, status),
        "tally": {"uphold": tally["uphold"], "void": tally["void"]},
    }


@proofs_router.get("/{proof_id}")
async def serve_proof(
    proof_id: int, session: AsyncSession = Depends(get_session), member=Depends(require_login)
):
    """Serve a complaint's image proof (login required). Only upload proofs have
    bytes here; telegram (legacy) proofs live in chat."""
    proof = await fines_repo.get_proof(session, proof_id)
    if proof is None or proof.source != ProofSource.UPLOAD:
        raise NotFound("No such image.")
    path = storage.proof_path(proof.ref)
    if path is None:
        raise NotFound("Image file is missing.")
    return FileResponse(path, media_type=proof.content_type or "application/octet-stream")
