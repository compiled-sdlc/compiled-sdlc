package org.springframework.samples.petclinic.visits.web;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.samples.petclinic.visits.model.Visit;
import org.springframework.samples.petclinic.visits.model.VisitRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-118, visits side: a lookup with nothing to look up is refused
 * before the database is troubled.
 */
@WebMvcTest(VisitResource.class)
@ActiveProfiles("test")
class EmptyBatchLookupAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VisitRepository visitRepository;

    @Test
    void shouldRefuseALookupWhoseParameterCarriesNothing() throws Exception {
        mvc.perform(get("/pets/visits?petId="))
            .andExpect(status().isBadRequest());

        verify(visitRepository, never()).findByPetIdIn(anyCollection());
    }

    @Test
    void shouldRefuseALookupOfNothingButSeparators() throws Exception {
        mvc.perform(get("/pets/visits?petId=,,"))
            .andExpect(status().isBadRequest());

        verify(visitRepository, never()).findByPetIdIn(anyCollection());
    }

    @Test
    void shouldRefuseALookupWithNoParameterAtAll() throws Exception {
        mvc.perform(get("/pets/visits"))
            .andExpect(status().isBadRequest());

        verify(visitRepository, never()).findByPetIdIn(anyCollection());
    }

    @Test
    void shouldStillAnswerALookupThatNamesPets() throws Exception {
        given(visitRepository.findByPetIdIn(anyCollection()))
            .willReturn(List.of(
                Visit.VisitBuilder.aVisit().id(1).petId(111).build(),
                Visit.VisitBuilder.aVisit().id(2).petId(222).build()));

        mvc.perform(get("/pets/visits?petId=111,222"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.items.length()").value(2))
            .andExpect(jsonPath("$.items[0].id").value(1));

        verify(visitRepository).findByPetIdIn(anyCollection());
    }
}
