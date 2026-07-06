from typing import Optional

from pydantic import BaseModel, Field


class Transaction(BaseModel):
    trans_num:    str           = Field(...,  example="2da90c7d74bd46a0caf3777415b3ebd3")
    amt:          float         = Field(...,  example=91.26)
    merchant:     str           = Field(...,  example="fraud_Hermann and Sons")
    category:     str           = Field(...,  example="shopping_pos")
    first:        Optional[str] = Field(None, example="Kristina",
                                        description="Utilisé uniquement pour recalculer id_client/diff_avg_amt")
    last:         Optional[str] = Field(None, example="Stewart",
                                        description="Utilisé uniquement pour recalculer id_client/diff_avg_amt")
    dob:          Optional[str] = Field(None, example="1971-04-25",
                                        description="Utilisé uniquement pour recalculer id_client/diff_avg_amt")
    gender:       Optional[str] = Field(None, example="F")
    city:         Optional[str] = Field(None, example="Newhall")
    state:        Optional[str] = Field(None, example="CA")
    zip:          Optional[int] = Field(None, example=91321)
    lat:          float         = Field(...,  example=34.3795)
    long:         float         = Field(...,  example=-118.523)
    city_pop:     Optional[int] = Field(None, example=34882)
    job:          Optional[str] = Field(None, example="Health physicist")
    merch_lat:    float         = Field(...,  example=34.886784)
    merch_long:   float         = Field(...,  example=-117.746728)
    current_time: Optional[int] = Field(None, example=1769445064133,
                                        description="Timestamp en millisecondes epoch")
    unix_time:    Optional[int] = Field(None, example=1371816865,
                                        description="Timestamp en secondes epoch (fallback)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "trans_num": "2da90c7d74bd46a0caf3777415b3ebd3",
                "amt": 91.26,
                "merchant": "fraud_Hermann and Sons",
                "category": "shopping_pos",
                "first": "Kristina",
                "last": "Stewart",
                "dob": "1971-04-25",
                "gender": "F",
                "city": "Newhall",
                "state": "CA",
                "zip": 91321,
                "lat": 34.3795,
                "long": -118.523,
                "city_pop": 34882,
                "job": "Health physicist",
                "merch_lat": 34.886784,
                "merch_long": -117.746728,
                "current_time": 1769445064133,
            }
        }
    }


class PredictionResponse(BaseModel):
    trans_num:   str
    is_fraud:    bool
    fraud_score: float = Field(..., description="Score de fraude [0, 1]")
    threshold:   float = Field(0.5, description="Seuil de décision")
